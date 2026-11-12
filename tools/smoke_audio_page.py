"""Real Chrome audio/RTC/IndexedDB QA using synthetic tracks, no real Meet."""

import asyncio
import io
import json
import os
import tempfile
import wave
import base64
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import ClientSession, web

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=('pcm.js','meet.js','translate.js','journal.js','transcript-format.js','pcm-worklet.js')
FIXTURE='''
window.runQA=async()=>{
 const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 const assert=(condition,message)=>{if(!condition)throw Error(message);};
 const sourceContext=new AudioContext();await sourceContext.resume();
 const oscillator=sourceContext.createConstantSource();oscillator.offset.value=.1;
 const destination=sourceContext.createMediaStreamDestination();oscillator.connect(destination);oscillator.start();
 const original=destination.stream.getAudioTracks()[0];
 const peer=new RTCPeerConnection();const sender=peer.addTrack(original,destination.stream);
 const canvas=document.createElement('canvas');canvas.width=16;canvas.height=16;canvas.getContext('2d').fillRect(0,0,16,16);
 const video=canvas.captureStream(5).getVideoTracks()[0];const videoSender=peer.addTrack(video,new MediaStream([video]));
 const frames=[];window.addEventListener('message',event=>{if(event.data?.ct==='microphone')frames.push(event.data.samples);});
 await window.__CTtranslate.start({sessionId:'qa',workletURL:'/pcm-worklet.js',echoGuard:false});
 assert(sender.track!==original,'track replacement failed');
 for(let i=0;i<100 && frames.length<6;i++)await wait(30);
 assert(frames.length>=3 && frames.every(frame=>frame.length===320 && frame.every(Number.isInteger)),'AudioWorklet framing failed');
 assert(frames.some(frame=>frame.some(sample=>sample!==0)),'synthetic microphone is silent');
 await window.__CTtranslate.audio({audio:WAV});
 sender.track.enabled=false;await wait(180);
 assert(frames.slice(-3).every(frame=>frame.every(sample=>sample===0)),'mute did not silence capture');
 await window.__CTtranslate.stop();assert(sender.track===original && !original.enabled,'mute/restore failed');
 original.enabled=true;
 await window.__CTtranslate.start({sessionId:'qa2',workletURL:'/pcm-worklet.js',echoGuard:false});
 window.postMessage({ct:'runtime-lost'},location.origin);
 for(let i=0;i<50 && sender.track!==original;i++)await wait(20);
 assert(sender.track===original,'runtime loss did not restore microphone');
 await window.__CTtranslate.start({sessionId:'qa3',workletURL:'/pcm-worklet.js',echoGuard:false});
 const changed=sourceContext.createMediaStreamDestination().stream.getAudioTracks()[0];
 await sender.replaceTrack(changed);await wait(160);
 assert(sender.track===changed,'newer Meet track was overwritten');
 assert(videoSender.track===video,'camera/video was changed');
 await CTJournal.putSession({id:'qa-session',started_at:Date.now(),source:'uk',target:'en',state:'stopped'});
 await CTJournal.record('qa-session',{type:'recognized',direction:'incoming',sequence:1,original:'<script>qa</script>'});
 await CTJournal.record('qa-session',{type:'translation',direction:'incoming',sequence:1,original:'<script>qa</script>',text:'translated'});
 const rows=await CTJournal.entries('qa-session');assert(rows.length===1 && rows[0].text==='translated','IndexedDB merge failed');
 const exported=CTTranscript.html((await CTJournal.sessions())[0],rows);
 assert(!exported.includes('<script>qa'),'unsafe transcript export');
 peer.close();oscillator.stop();video.stop();original.stop();changed.stop();await sourceContext.close();
 return {chrome_audio_worklet:true,pcm_frames:frames.length,microphone_restored:true,mute_preserved:true,
   runtime_loss_restored:true,newer_track_preserved:true,video_untouched:true,indexeddb_journal:true,
   full_meet_call_verified:false,chrome_tab_capture_verified:false};
};
'''


async def main():
    candidates=[Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Google/Chrome/Application/chrome.exe',
                Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Google/Chrome/Application/chrome.exe']
    chrome=next((path for path in candidates if path.is_file()),None)
    if chrome is None:raise RuntimeError('Chrome not found')
    output=io.BytesIO()
    with wave.open(output,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(bytes(3200))
    script=FIXTURE.replace('audio:WAV','audio:'+json.dumps(base64.b64encode(output.getvalue()).decode('ascii')))
    async def page(request):
        body='<!doctype html><meta charset="utf-8"><title>Synthetic audio QA</title>'+''.join(
            f'<script src="/{name}"></script>' for name in SCRIPTS if name!='pcm-worklet.js')+'<script src="/fixture.js"></script>'
        return web.Response(text=body,content_type='text/html')
    async def asset(request):
        name=request.match_info['name']
        if name=='fixture.js':return web.Response(text=script,content_type='text/javascript')
        if name not in SCRIPTS:raise web.HTTPNotFound()
        return web.Response(body=(ROOT/'extension'/name).read_bytes(),content_type='text/javascript')
    app=web.Application();app.router.add_get('/',page);app.router.add_get('/{name}',asset)
    runner=web.AppRunner(app,access_log=None);await runner.setup()
    process=None
    try:
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        with tempfile.TemporaryDirectory(prefix='ct-browser-audio-') as temp:
            profile=Path(temp)/'profile'
            process=await asyncio.create_subprocess_exec(str(chrome),'--headless=new','--disable-gpu','--no-first-run',
                '--no-default-browser-check','--disable-background-networking','--mute-audio','--autoplay-policy=no-user-gesture-required',
                '--user-data-dir='+str(profile),'--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','about:blank',
                stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
            try:
                # Chrome can hold DevToolsActivePort exclusively on Windows.
                # Read this owned process's endpoint announcement instead.
                async with asyncio.timeout(15):
                    while True:
                        line=await process.stderr.readline()
                        if not line:raise RuntimeError('Headless Chrome exited before DevTools startup')
                        value=line.decode('utf-8',errors='replace').strip()
                        if value.startswith('DevTools listening on '):
                            debug_port=urlsplit(value.removeprefix('DevTools listening on ')).port
                            break
                drain=asyncio.create_task(process.stderr.read())
                async with ClientSession() as session:
                    async with session.get(f'http://127.0.0.1:{debug_port}/json/list') as response:targets=await response.json()
                    target=next(item for item in targets if item['type']=='page')
                    async with session.ws_connect(target['webSocketDebuggerUrl']) as socket:
                        identifier=0
                        async def command(method,params):
                            nonlocal identifier
                            identifier+=1;current_id=identifier
                            await socket.send_json({'id':current_id,'method':method,'params':params})
                            async with asyncio.timeout(30):
                                async for incoming in socket:
                                    value=json.loads(incoming.data)
                                    if value.get('id')==current_id:return value
                            raise RuntimeError('CDP disconnected')
                        await command('Page.navigate',{'url':f'http://127.0.0.1:{port}/'})
                        for _ in range(100):
                            ready=await command('Runtime.evaluate',{'expression':'typeof window.runQA === "function"','returnByValue':True})
                            if ready.get('result',{}).get('result',{}).get('value'):break
                            await asyncio.sleep(.05)
                        result=await command('Runtime.evaluate',{'expression':'window.runQA()','awaitPromise':True,'returnByValue':True})
                        if 'exceptionDetails' in result.get('result',{}):
                            detail=result['result']['exceptionDetails'].get('exception',{}).get('description','')
                            raise RuntimeError('Synthetic browser audio assertions failed: '+str(detail)[:400])
                        report=result['result']['result']['value']
                        if not report.get('chrome_audio_worklet'):raise RuntimeError('Audio browser proof missing')
                        destination=ROOT/'build'/'browser-audio-smoke.json';destination.parent.mkdir(parents=True,exist_ok=True)
                        destination.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))
                        await socket.send_json({'id':identifier+1,'method':'Browser.close'})
                await asyncio.wait_for(process.wait(),timeout=15)
                await drain
            finally:
                if process.returncode is None:
                    process.kill();await process.wait()
    finally:
        await runner.cleanup()


if __name__=='__main__':
    asyncio.run(main())
