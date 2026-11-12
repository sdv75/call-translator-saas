const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function fixture() {
  let listener,capture,socket;const sent=[],sources=[],intervals=new Set(),gains=[],timers=new Map();
  const track={stopped:false,addEventListener(){},stop(){this.stopped=true;}};
  class Socket {
    static OPEN=1;
    constructor(){this.readyState=1;this.bufferedAmount=0;this.sent=[];socket=this;setImmediate(()=>this.onopen?.());}
    send(data){
      this.sent.push(data);
      if(typeof data==='string'){
        const message=JSON.parse(data);
        if(message.token) setImmediate(()=>this.emit({type:'ready',call_id:'call-test',sample_rate:16000,frame_ms:20}));
        if(message.type==='stop') setImmediate(()=>{
          this.emit({type:'recognized',direction:'incoming',sequence:999,original:'late'});
          this.emit({type:'translation',direction:'incoming',sequence:999,original:'late',text:'tail',language:'uk'});
          this.emit({type:'stopped',reason:'user_stop',transcript_complete:true});
        });
      }
    }
    emit(data){this.onmessage({data:JSON.stringify(data)});}
    close(){if(this.readyState===3)return;this.readyState=3;this.onclose?.();}
  }
  class Context {
    constructor(){this.currentTime=0;this.destination={};}
    async resume(){}async close(){}async decodeAudioData(){return {duration:1};}
    createMediaStreamSource(){return {connect(node){return node;}};}
    createGain(){const node={gain:{},connect(){return this;},disconnect(){}};gains.push(node);return node;}
    createBufferSource(){const source={connect(gain){this.gain=gain;return gain;},start(when){this.when=when;sources.push(this);},stop(){this.stopped=true;},disconnect(){}};return source;}
  }
  const context={console,URL,ArrayBuffer,DataView,Uint8Array,
    setTimeout:(fn,ms)=>{const timer=setTimeout(()=>{timers.delete(timer);fn();},ms);timers.set(timer,ms);return timer;},
    clearTimeout:timer=>{timers.delete(timer);clearTimeout(timer);},
    setInterval:fn=>{intervals.add(fn);return fn;},clearInterval:fn=>intervals.delete(fn),
    atob:value=>Buffer.from(value,'base64').toString('binary'),
    navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[track]})}},AudioContext:Context,WebSocket:Socket,
    CTpcm:async(ctx,stream,callback)=>{capture=callback;return ()=>{};},
    chrome:{runtime:{id:'test',getURL:name=>'chrome-extension://test/'+name,onMessage:{addListener:fn=>{listener=fn;}},
      sendMessage:async message=>{
        sent.push(message);
        if(message.type==='native-synthesize'){
          if(message.text==='slow')await wait(35);
          return {ok:true,result:{audio:Buffer.from('RIFF'+message.text).toString('base64'),synthesis_ms:1}};
        }
        return {ok:true,result:{ok:true}};
      }}}};
  vm.createContext(context);
  for(const file of ['protocol.js','audio-protocol.js','offscreen.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,file),'utf8'),context);
  const command=(type,extra={})=>new Promise(resolve=>listener({target:'offscreen',type,sessionId:'session-test',...extra},{id:'test'},resolve));
  return {command,sent,sources,gains,track,intervals,timers,get socket(){return socket;},capture:()=>capture(Array(320).fill(0))};
}
(async()=>{
  {
    const f=fixture();assert((await f.command('start',{service:'https://saas.example/base',credential:'TEST-ONLY',streamId:'stream',source:'uk',language:'en'})).ok);
    f.capture();assert.equal(f.socket.sent.filter(item=>item instanceof ArrayBuffer).length,0,'No billing audio during startup');
    await f.command('activate');f.capture();await f.command('pcm',{samples:Array(320).fill(0)});
    const packets=f.socket.sent.filter(item=>item instanceof ArrayBuffer);
    assert.deepEqual(packets.map(item=>new DataView(item).getUint8(0)),[1,0]);
    f.socket.emit({type:'interim',direction:'incoming',sequence:1,original:'partial source'});
    f.socket.emit({type:'recognized',direction:'incoming',sequence:1,original:'source'});
    f.socket.emit({type:'translation',direction:'incoming',sequence:1,original:'source',text:'incoming',language:'uk',timing:{translation_ms:120}});
    f.socket.emit({type:'translation',direction:'outgoing',sequence:1,original:'source',text:'outgoing',language:'en'});
    f.socket.emit({type:'translation',direction:'outgoing',sequence:1,original:'source',text:'outgoing',language:'en'});
    await wait(25);
    const page=f.sent.filter(item=>item.type==='page-audio');assert.equal(page.length,1);
    assert.equal(Buffer.from(page[0].audio,'base64').toString(),'RIFFoutgoing');
    assert.equal(f.sent.filter(item=>item.type==='native-synthesize').length,2);
    assert(f.sent.some(item=>item.type==='audio-live'&&item.event.type==='interim'));
    const metric=f.sent.find(item=>item.type==='audio-metrics'&&item.event.direction==='incoming');
    assert(metric && metric.event.timing.translation_ms===120 && metric.event.timing.after_recognition_ms>=0);
      assert.equal(metric.event.timing.synthesis_ms,1);assert(metric.event.timing.native_transfer_ms>=0);
    assert(f.sent.findIndex(item=>item.type==='audio-journal')<f.sent.findIndex(item=>item.type==='native-synthesize'));
    const incoming=f.sources.find(item=>item.gain.gain.value===1),outgoing=f.sources.find(item=>item.gain.gain.value===0);
    assert(incoming && outgoing);await f.command('monitor',{enabled:true});assert.equal(outgoing.gain.gain.value,.55);assert.equal(incoming.gain.gain.value,1);
    const before=f.sent.filter(item=>item.type==='native-synthesize').length;
    assert((await f.command('stop')).complete);
    await wait(10);assert(f.track.stopped);assert(f.sources.every(item=>item.stopped));
    assert.equal(f.sent.filter(item=>item.type==='native-synthesize').length,before,'Stop tail must be journaled without new speech');
    assert(f.sent.some(item=>item.type==='audio-journal' && item.event.sequence===999));assert.equal(f.intervals.size,0);assert.equal(f.timers.size,0,JSON.stringify([...f.timers.values()]));
  }
  {
    const f=fixture();await f.command('start',{service:'http://localhost:5086',credential:'TEST',streamId:'stream',source:'uk',language:'en'});await f.command('activate');
    f.socket.emit({type:'translation',direction:'outgoing',sequence:1,original:'a',text:'slow',language:'en'});
    f.socket.emit({type:'translation',direction:'outgoing',sequence:2,original:'b',text:'fast',language:'en'});
    await wait(80);assert.deepEqual(f.sent.filter(item=>item.type==='page-audio').map(item=>Buffer.from(item.audio,'base64').toString()),['RIFFslow','RIFFfast']);
    f.socket.emit({type:'translation',direction:'outgoing',sequence:3,original:'c',text:'slow',language:'en'});
    await wait(2);await f.command('stop');const played=f.sent.filter(item=>item.type==='page-audio').length;
    await wait(50);assert.equal(f.sent.filter(item=>item.type==='page-audio').length,played,'No late playback after Stop');assert.equal(f.timers.size,0,JSON.stringify([...f.timers.values()]));
  }
  {
    const f=fixture();await f.command('start',{service:'https://saas.example',credential:'TEST',streamId:'stream',source:'uk',language:'en',echoGuard:true,hearOwnTranslation:true});await f.command('activate');
    f.socket.emit({type:'translation',direction:'outgoing',sequence:1,original:'a',text:'test',language:'en'});
    await wait(25);
    const guard=f.sent.findIndex(item=>item.type==='local-playback'),page=f.sent.findIndex(item=>item.type==='page-audio');
    assert(guard>=0 && guard<page,'Microphone guard must be armed before audible own translation');
    assert.equal(f.sent[guard].durationMs,1000);
    assert.equal(f.sources.length,1,'Monitor uses the same synthesized WAV, no extra synthesis');
    await f.command('stop');
  }
  {
    const f=fixture();await f.command('start',{service:'https://saas.example',credential:'TEST',streamId:'stream',source:'uk',language:'en'});await f.command('activate');
    f.socket.bufferedAmount=40000;f.capture();await wait(10);
    assert(f.sent.some(item=>item.type==='audio-failed' && item.reason==='network_backlog'));
    assert.equal(f.socket.sent.filter(item=>item instanceof ArrayBuffer).length,0);await f.command('stop');assert.equal(f.timers.size,0,JSON.stringify([...f.timers.values()]));
  }
  {
    const f=fixture();await f.command('start',{service:'https://saas.example',credential:'TEST',streamId:'stream',source:'uk',language:'en'});await f.command('activate');
    const text='Первая фраза. Остання фраза перевірки: усе збережено.';
    f.socket.emit({type:'translation',direction:'incoming',sequence:1,original:'source',text,language:'uk'});
    await wait(30);
    const requests=f.sent.filter(item=>item.type==='native-synthesize');
    assert.equal(requests.length,2);assert.equal(requests.map(item=>item.text).join(''),text);
    assert.equal(f.sources.length,2,'Both sentences must reach ordered playback');
    await f.command('stop');
  }
  console.log('Offscreen duplex: startup gate, direction isolation, ordered TTS, deduplication, tail journal, Stop and congestion passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
