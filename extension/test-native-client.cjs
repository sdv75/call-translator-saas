const assert = require('node:assert/strict');
require('./protocol.js');
const LocalVoiceClient = require('./native-client.js');
function fixture() {
  let message, disconnect;
  const port = {sent:[], onMessage:{addListener(fn){message=fn;}},
    onDisconnect:{addListener(fn){disconnect=fn;}}, postMessage(value){this.sent.push(value);},
    disconnect(){}, emit(value){message(value);}, lose(){disconnect();}};
  const runtime = {connectNative(name){assert.equal(name,'org.call_translator.saas.local'); return port;}};
  return {client:new LocalVoiceClient(runtime),port};
}
(async () => {
  {
    const {client,port}=fixture();
    let request=client.request('status');
    port.emit({id:1,protocol:1,ready:false,voices:[],version:'0.1.0'});
    assert.equal((await request).ready,false);
    request=client.request('status');
    port.emit({id:2,protocol:1,ready:true,voices:[{id:'uk-basic'}],version:'0.1.0'});
    assert.equal((await request).ready,true); client.close();
  }
  {
    const {client,port}=fixture();
    const request=client.request('preview-voice',{voice_id:'uk-basic'});
    const wav=Buffer.alloc(48); wav.write('RIFF',0); wav.write('WAVE',8);
    port.emit({id:1,type:'audio-chunk',index:0,data:wav.toString('base64')});
    port.emit({id:1,type:'audio-end',chunks:1,bytes:wav.length,synthesis_ms:12});
    const reply=await request;
    assert.equal(Buffer.from(reply.audio,'base64').length,48);assert.equal(reply.synthesis_ms,12);client.close();
  }
  {
    const {client,port}=fixture();
    const request=client.request('preview-voice',{voice_id:'uk-basic'});
    port.emit({id:1,type:'audio-chunk',index:3,data:'AAAA'});
    await assert.rejects(request,/Некорректный/); client.close();
  }
  {
    const {client,port}=fixture();
    const request=client.request('status'); port.lose();
    await assert.rejects(request,/подключить/); assert.equal(client.pending.size,0);
  }
  {
    const {client}=fixture();
    const pending=Array.from({length:4},()=>client.request('status').catch(()=>{}));
    await assert.rejects(client.request('status'),/занята/);
    client.close(); await Promise.all(pending);
  }
  console.log('Native voice client: status IDs, WAV framing, ordering, disconnect and queue checks passed');
})().catch(error=>{console.error(error); process.exitCode=1;});
