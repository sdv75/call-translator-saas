const assert=require('node:assert/strict');
global.crypto=require('node:crypto').webcrypto;
require('./protocol.js');
require('./service-config.js');
require('./language-library.js');
const Controller=require('./call-controller.js');
const tick=()=>new Promise(setImmediate);
function fixture() {
  const actions=[],saved=[],events=[],storage={};
  let exists=false,disabled=false,failJournal=false,holdBegin=false,beginReject;
  const voice={requests:[],close(){actions.push('native-close');beginReject?.(Error('cancelled'));},async request(type,payload){
    this.requests.push({type,payload});actions.push(type);
    if(type==='begin-call' && holdBegin) return new Promise((resolve,reject)=>{beginReject=reject;});
    if(type==='status')return {ready:true,voices:[{id:'uk',language:'uk'},{id:'en',language:'en'}],selected:{incoming:'uk',outgoing:'en'}};
    return type==='synthesize'?{audio:'fixture'}:{};
  }};
  const chrome={storage:{local:{get:async()=>({service:CTService.url,credential:'TEST-DEVICE-CREDENTIAL'})},
    session:{set:async data=>Object.assign(storage,data),get:async key=>({[key]:storage[key]}),remove:async key=>{delete storage[key];}}},
    runtime:{getURL:name=>'chrome-extension://test/'+name,getContexts:async()=>exists?[{}]:[],
      sendMessage:async message=>{actions.push('offscreen-'+message.type);return {ok:true,complete:true};}},
    tabs:{query:async()=>[{id:7,url:'https://meet.google.com/abc-defg-hij'}],sendMessage:async()=>({ok:true})},
    scripting:{executeScript:async options=>{actions.push('page-'+options.args[0]);
      assert(!JSON.stringify(options.args).includes('TEST-DEVICE-CREDENTIAL'),'Credential must never enter MAIN world');
      return [{result:options.args[0]==='status'?{senders:1}:undefined}];}},
    offscreen:{createDocument:async()=>{exists=true;actions.push('create-offscreen');},closeDocument:async()=>{exists=false;actions.push('close-offscreen');}},
    tabCapture:{getMediaStreamId:async()=>{actions.push('capture-id');return 'TEST-STREAM';}}};
  const journal={putSession:async value=>{if(failJournal) throw Error('quota');saved.push({...value});},record:async(session,event)=>events.push({session,event})};
  const api=async(base,path)=>{assert.equal(base,CTService.url);return path==='/health'?{audio_enabled:!disabled}:{balance_ms:300000,active_call:null};};
  const controller=new Controller(chrome,voice,journal,api);
  return {controller,voice,chrome,actions,saved,events,storage,setDisabled:value=>disabled=value,setFailJournal:value=>failJournal=value,setHold:value=>holdBegin=value};
}
const options={source:'uk',language:'en'};
(async()=>{
  {
    const f=fixture(),files=[];
    f.controller.files={exportSession:async session=>files.push(session)};
    await f.controller.start(options);await f.controller.stop();
    assert.equal(files.length,1);assert.equal(files[0].state,'stopped');
    assert(f.actions.indexOf('page-stop')<f.actions.indexOf('end-call'),'Restore microphone before file IO');
  }
  {
    const f=fixture();await f.controller.start(options);
    assert.equal(f.controller.status().phase,'active');
    assert.match(f.controller.status().text,/Всё готово, начинайте разговор/);
    assert(f.actions.indexOf('begin-call')<f.actions.indexOf('capture-id'));
    assert(f.actions.indexOf('offscreen-start')<f.actions.indexOf('page-start'));
    assert(f.actions.indexOf('page-start')<f.actions.indexOf('offscreen-activate'));
    const id=f.controller.run.id;
    await assert.rejects(f.controller.start(options),/уже/);
    assert.equal(f.controller.run.id,id);
    const before=f.actions.length;
    await f.controller.event({type:'pcm',sessionId:'stale',samples:[]},{tab:{id:7}});
    assert.equal(f.actions.length,before);
    await assert.rejects(f.controller.event({type:'native-synthesize',sessionId:id,text:'x'},{tab:{id:7}}),/Недопустимый/);
    await f.controller.event({type:'pcm',sessionId:id,samples:Array(320).fill(0)},{tab:{id:7}});
    assert(f.actions.includes('offscreen-pcm'));
    await f.controller.stop();
    assert.equal(f.controller.run,null);assert.equal(f.controller.status().phase,'stopped');
    assert(f.actions.indexOf('page-stop')<f.actions.indexOf('end-call'));
    assert(!f.storage.audioSession);assert.equal(f.saved.at(-1).state,'stopped');
  }
  {
    const f=fixture();f.setDisabled(true);
    await assert.rejects(f.controller.start(options),/выключены/);
    assert(!f.actions.includes('capture-id'));assert(!f.actions.includes('page-start'));
    assert(!f.actions.includes('begin-call'));assert.equal(f.controller.run,null);
    assert.match(f.controller.status().text,/выключены/);
    assert.equal(f.controller.status().code,'start_failed');
  }
  {
    const f=fixture();f.setHold(true);
    const starting=f.controller.start(options);
    const rejected=assert.rejects(starting);
    while(!f.actions.includes('begin-call')) await tick();
    await f.controller.stop();await rejected;
    assert.equal(f.controller.run,null);assert(!f.actions.includes('page-start'));assert(!f.actions.includes('capture-id'));
    f.setHold(false);await f.controller.start(options);await f.controller.stop();
  }
  {
    const f=fixture();await f.controller.start(options);f.setFailJournal(true);
    await f.controller.stop();assert.equal(f.controller.run,null);assert.equal(f.controller.status().phase,'error');
    assert(f.actions.includes('page-stop'));assert(f.actions.includes('end-call'));
  }
  {
    const f=fixture();await f.controller.start(options);
    const sender={url:f.chrome.runtime.getURL('offscreen.html')},sessionId=f.controller.run.id;
    await f.controller.event({type:'audio-live',sessionId,event:{type:'interim',direction:'outgoing',sequence:1,original:'partial'}},sender);
    assert.equal(f.events.length,0,'Interim is not a saved transcript');
    await f.controller.event({type:'audio-journal',sessionId,event:{type:'recognized',direction:'outgoing',sequence:1,original:'Остання фраза перевірки:'}},sender);
    await f.controller.event({type:'audio-journal',sessionId,event:{type:'translation',direction:'outgoing',sequence:1,text:'Последняя фраза проверки:'}},sender);
    assert.equal(f.storage.liveConversation.events.length,1);
    assert.equal(f.storage.liveConversation.events[0].original,'Остання фраза перевірки:');
    assert.equal(f.storage.liveConversation.partial.outgoing,'');
    await f.controller.stop();
  }
  {
    const f=fixture();await f.controller.start(options);
    const recovered=new Controller(f.chrome,f.voice,{putSession:async value=>f.saved.push(value)},async()=>{});
    await recovered.recover();assert.equal(recovered.status().phase,'error');
    assert.equal(f.saved.at(-1).state,'interrupted');assert(!f.storage.audioSession);
    await f.controller.stop();
  }
  console.log('Call controller: preflight, cancellation, stale frames, privilege boundary, restore and recovery passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
