"""Two fixed synthetic speakers through live SaaS providers and local voices.

Temporary test database/credentials only. No real account, Meet, microphone,
camera, transcript upload, or playback through the user's audio device.
"""

import asyncio
import base64
import io
import json
import tempfile
import wave
from dataclasses import replace
from pathlib import Path

import numpy as np
from aiohttp import ClientSession, WSMsgType, web

from local_component.call_translator_local.voices import VoiceStore
from tools.native_probe_client import NativeProbeClient
from server.app import IDENTITY, STORE, create_app
from server.config import Settings

REPORT={'real_provider_requests':False,'google_login_used_in_probe':False,'real_user_balance_touched':False,
        'full_meet_call_verified':False,'listening_test_performed':False,'directions':{},'events':{}}


def stage(value):
    REPORT['stage']=value
    Path('build').mkdir(exist_ok=True)
    Path('build/duplex-local-probe.json').write_text(json.dumps(REPORT,indent=2)+'\n',encoding='utf-8')


def pcm(audio):
    with wave.open(io.BytesIO(audio),'rb') as source:
        rate=source.getframerate();samples=np.frombuffer(source.readframes(source.getnframes()),dtype='<i2')
    positions=np.arange(int(len(samples)*16000/rate))*rate/16000
    return np.interp(positions,np.arange(len(samples)),samples).astype('<i2').tobytes()


async def main():
    stage('prepare-fixed-fixtures')
    trust=json.loads(Path('local_component/call_translator_local/catalog-trust.json').read_text(encoding='utf-8'))
    store=VoiceStore(Path('build/local-voices'),trust)
    store.select('incoming','uk-basic');store.select('outgoing','en-basic')
    local=NativeProbeClient();await local.start(Path('build/local-voices'))
    REPORT['native_timings']=local.timings
    try:
        stage('synthesize-uk-fixture')
        outgoing=pcm(await local.request('preview-voice',voice_id='uk-basic'))
        stage('synthesize-en-fixture')
        incoming=pcm(await local.request('preview-voice',voice_id='en-basic'))
    except BaseException:
        await local.close()
        raise
    length=(max(len(outgoing),len(incoming))+639)//640*640+640*30
    if length>640*500:raise ValueError('Fixture exceeds bounded duration')
    outgoing=outgoing.ljust(length,b'\0');incoming=incoming.ljust(length,b'\0')
    try:
        stage('warm-both-local-voices')
        ready=await local.request('begin-call',source='uk',target='en')
        if ready.get('type')!='call-ready':raise ValueError('Local pair not ready')
    except BaseException:
        await local.close()
        raise
    report=REPORT
    try:
        with tempfile.TemporaryDirectory(prefix='ct-duplex-probe-') as temp:
            settings=replace(Settings.from_env(),database=Path(temp)/'probe.sqlite3',experimental_audio=True,public_url='http://localhost:5086')
            app=create_app(settings);runner=web.AppRunner(app,access_log=None);await runner.setup()
            try:
                site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
                account=app[STORE].register('internal-duplex-probe-not-google-user')
                token,_=app[IDENTITY].redeem_pairing(app[IDENTITY].new_pairing(account))
                complete=asyncio.Event();finishing=False
                async with ClientSession() as session:
                    stage('connect-providers');report['real_provider_requests']=True
                    async with session.ws_connect(f'http://127.0.0.1:{port}/ws') as socket:
                        await socket.send_json({'token':token,'source':'uk','target':'en'})
                        started=await socket.receive_json(timeout=25)
                        if started.get('type')!='ready':raise ValueError('Server pair not ready')
                        async def results():
                            identifier=10
                            async for message in socket:
                                if message.type!=WSMsgType.TEXT:continue
                                result=json.loads(message.data)
                                if result.get('type') in ('recognized','translation','stopped','balance'):
                                    name=result['type'];report['events'][name]=report['events'].get(name,0)+1
                                if result.get('type')=='stopped':
                                    report['server_stop_reason']=result.get('reason');complete.set();break
                                if result.get('type')!='translation' or finishing:continue
                                identifier+=1
                                audio=await local.request('synthesize',direction=result['direction'],text=result['text'])
                                with wave.open(io.BytesIO(audio),'rb') as wav:
                                    metrics={'language':result['language'],'sample_rate':wav.getframerate(),
                                             'audio_seconds':wav.getnframes()/wav.getframerate(),'wav_bytes':len(audio)}
                                report['directions'][result['direction']]=metrics
                                stage('local-output-received')
                                Path('build/duplex-output-'+result['direction']+'.wav').write_bytes(audio)
                                if len(report['directions'])==2:complete.set()
                        reader=asyncio.create_task(results())
                        try:
                            stage('send-fixed-audio')
                            for offset in range(0,length,640):
                                await socket.send_bytes(b'\x00'+outgoing[offset:offset+640])
                                await socket.send_bytes(b'\x01'+incoming[offset:offset+640])
                                await asyncio.sleep(.02)
                            stage('wait-both-local-outputs')
                            await asyncio.wait_for(complete.wait(),timeout=20)
                            finishing=True;await socket.send_json({'type':'stop'})
                            stage('drain-stop')
                            await asyncio.wait_for(reader,timeout=10)
                        finally:
                            if not reader.done():reader.cancel()
                            finished=await asyncio.gather(reader,return_exceptions=True)
                            if isinstance(finished[0],Exception):report['reader_error_type']=type(finished[0]).__name__
                row=app[STORE].db.execute('SELECT speech_ms,reserve_ms,state FROM calls WHERE id=?',(started['call_id'],)).fetchone()
                report.update({'fixture_ms_per_direction':length//640*20,'billed_speech_ms':row[0],
                    'unused_reserve_released':row[1]==0 and app[STORE].balance(account)==300000-row[0],
                    'server_call_stopped':row[2]=='stopped',
                    'sent_stt_audio_ms':app[STORE].db.execute('SELECT sum(audio_ms) FROM stt_usage').fetchone()[0]})
                report['status']='ok' if len(report['directions'])==2 and report['unused_reserve_released'] else 'failed'
            finally:await runner.cleanup()
    finally:await local.close()
    stage('complete')
    print(json.dumps(report,indent=2))
    if report['status']!='ok':raise SystemExit(1)


if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as exc:
        REPORT.update(status='failed',error_type=type(exc).__name__)
        Path('build/duplex-local-probe.json').write_text(json.dumps(REPORT,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(REPORT,indent=2))
        raise SystemExit(1)
