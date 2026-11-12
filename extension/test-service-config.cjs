'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const service=require('./service-config.js');
const protocol=require('./protocol.js');
let listener,config={service:'http://localhost:5086',credential:'LOCAL-ONLY'},requests=[];
const chrome={runtime:{id:'test',getURL:name=>'chrome-extension://test/'+name,onMessage:{addListener:fn=>listener=fn}},
  storage:{local:{setAccessLevel:async()=>{},get:async()=>({...config}),set:async value=>Object.assign(config,value),
    remove:async keys=>{for(const key of keys)delete config[key];}}},
  tabs:{onRemoved:{addListener(){}},onUpdated:{addListener(){}}}};
const context={chrome,CTService:service,CTProtocol:protocol,importScripts(){},CTJournal:{sessions:async()=>[]},CTTranscriptFiles:{configure(){},recover:async()=>{}},
  AbortSignal,LocalVoiceClient:class{},CTCallController:class{async recover(){} async stop(){} async publish(){}},
  fetch:async(url,options)=>{
    requests.push({url,options});assert(url.startsWith(service.url+'/'));
    return {ok:true,json:async()=>url.endsWith('/redeem')?{access_token:'VPS-DEVICE',device_id:'test-device'}:{balance_ms:300000}};
  }};
vm.runInNewContext(fs.readFileSync(__dirname+'/background.js','utf8'),context);
const send=message=>new Promise(resolve=>listener(message,{id:'test',url:chrome.runtime.getURL('popup.html')},resolve));
(async()=>{
  assert.equal(new URL(service.url).protocol,'https:');
  assert.equal((await send({type:'state'})).result.connected,false);
  assert.equal(requests.length,0,'A local credential must never be sent to the VPS');
  await send({type:'unlink'});
  assert.equal(requests.length,0,'Unlink must not contact a previous endpoint');
  await send({type:'pair',service:'https://untrusted.invalid',code:'a'.repeat(43)});
  assert.equal(requests[0].url,service.url+'/api/devices/redeem');
  assert.equal(config.service,service.url);
  assert.equal((await send({type:'state'})).result.connected,true);
  assert.equal(requests[1].options.headers.Authorization,'Bearer VPS-DEVICE');
  const manifest=JSON.parse(fs.readFileSync(__dirname+'/manifest.json','utf8'));
  assert(manifest.host_permissions.includes(new URL(service.url).origin+'/*'));
  assert(!manifest.optional_host_permissions?.some(origin=>origin.includes('*://') || origin==='https://*/*'));
  console.log('Fixed service: ignores endpoint overrides, isolates old local credentials and limits host permissions');
})().catch(error=>{console.error(error);process.exitCode=1;});
