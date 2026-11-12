'use strict';
let current = null;
const clockNow=()=>globalThis.performance?.now?.()??Date.now();
const notify = (type,payload={}) => chrome.runtime.sendMessage({type,...payload}).then(response=>{
  if (response?.error || response?.ok===false) throw Error('Связь с расширением потеряна.');
  const result=response?.result ?? response;
  if(result?.ok===false) throw Error('Связь с расширением потеряна.');
  return result;
});
function fail(state,reason) {
  if (current!==state || state.finishing || state.failed) return;
  state.failed=true; state.active=false;
  state.ws?.close();
  notify('audio-failed',{sessionId:state.id,reason}).catch(()=>stop());
}
function send(state,direction,samples) {
  if (current!==state || !state.active || state.ws.readyState!==WebSocket.OPEN) return;
  if (state.ws.bufferedAmount>32768) { fail(state,'network_backlog'); return; }
  try { state.ws.send(CTAudio.frame(direction,samples)); }
  catch { fail(state,'invalid_audio'); }
}
async function stop() {
  const state=current;
  if (!state) return {complete:true};
  if (state.stopping) return state.stopping;
  state.active=false; state.finishing=true;
  clearInterval(state.heartbeat);
  state.capture?.(); state.stream?.getTracks().forEach(track=>track.stop());
  for (const source of state.sources) { try { source.stop(); } catch {} }
  state.sources.clear();
  state.stopping=(async()=>{
    let complete=false;
    if (state.ws?.readyState===WebSocket.OPEN) {
      complete=await new Promise(resolve=>{
        const timer=setTimeout(()=>resolve(false),8000);
        state.finish=value=>{clearTimeout(timer);resolve(value);};
        state.ws.send(JSON.stringify({type:'stop'}));
      });
    }
    state.ws?.close();
    await state.journal.catch(()=>{});
    if (current===state) current=null;
    await state.context?.close();
    return {complete};
  })();
  return state.stopping;
}
async function localPlayback(state,audio,direction) {
  const decodeStart=clockNow();
  const data=Uint8Array.from(atob(audio),char=>char.charCodeAt(0)).buffer;
  const buffer=await state.context.decodeAudioData(data);
  const decodeMs=Math.round(clockNow()-decodeStart),routingStart=clockNow();
  if (current!==state || !state.active) return;
  const when=Math.max(state.context.currentTime,state.next[direction]);
  if (when-state.context.currentTime>30) throw Error('Очередь воспроизведения переполнена.');
  if(state.echoGuard && (direction==='incoming' || state.hearOwn))
    await notify('local-playback',{sessionId:state.id,delayMs:Math.max(0,when-state.context.currentTime)*1000,durationMs:buffer.duration*1000});
  if (direction==='outgoing') {
    await notify('page-audio',{sessionId:state.id,audio});
  }
  if (current!==state || !state.active) return;
  const source=state.context.createBufferSource(), gain=state.context.createGain();
  source.buffer=buffer; gain.gain.value=direction==='outgoing' ? (state.hearOwn ? 0.55 : 0) : 1;
  if(direction==='outgoing') state.monitors.add(gain);
  source.connect(gain).connect(state.context.destination); state.sources.add(source);
  source.onended=()=>{state.sources.delete(source);state.monitors.delete(gain);source.disconnect();gain.disconnect();};
  state.next[direction]=when+buffer.duration; source.start(when);
  source.until=when+buffer.duration;source.direction=direction;
  return {decode_ms:decodeMs,routing_ms:Math.round(clockNow()-routingStart),playback_queue_ms:Math.round(Math.max(0,when-state.context.currentTime)*1000)};
}
async function protectPlayingAudio(state){
  if(!state.echoGuard || !state.active)return;
  const until=Math.max(state.context.currentTime,...[...state.sources]
    .filter(source=>source.direction==='incoming'||state.hearOwn).map(source=>source.until||0));
  if(until>state.context.currentTime)await notify('local-playback',{sessionId:state.id,delayMs:0,durationMs:(until-state.context.currentTime)*1000});
}
async function start(message) {
  await stop();
  const state={id:message.sessionId,active:false,connected:false,finishing:false,failed:false,
    hearOwn:message.hearOwnTranslation===true,echoGuard:message.echoGuard===true,source:message.source,target:message.language,
    sources:new Set(),monitors:new Set(),next:{incoming:0,outgoing:0},chains:{incoming:Promise.resolve(),outgoing:Promise.resolve()},
    counts:{incoming:0,outgoing:0},sequences:{incoming:0,outgoing:0},recognizedAt:new Map(),journal:Promise.resolve()};
  current=state;
  try {
    state.stream=await navigator.mediaDevices.getUserMedia({audio:{mandatory:{chromeMediaSource:'tab',chromeMediaSourceId:message.streamId}},video:false});
    state.stream.getTracks().forEach(track=>track.addEventListener('ended',()=>fail(state,'capture_ended')));
    state.context=new AudioContext(); await state.context.resume();
    const original=state.context.createMediaStreamSource(state.stream), gain=state.context.createGain();
    gain.gain.value=.15; original.connect(gain).connect(state.context.destination);
    state.ws=new WebSocket(CTAudio.websocketURL(message.service));
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('Сервер не ответил вовремя.')),30000);
      const done=value=>{clearTimeout(timer);resolve(value);};
      state.ws.onopen=()=>state.ws.send(JSON.stringify({token:message.credential,source:message.source,target:message.language,live_text:true}));
      state.ws.onerror=()=>{clearTimeout(timer);reject(Error('Нет соединения с сервером.'));fail(state,'network_error');};
      state.ws.onclose=()=>{
        clearTimeout(timer);reject(Error('Соединение закрыто.'));state.finish?.(false);
        if (!state.finishing) fail(state,'network_error');
      };
      state.ws.onmessage=event=>{
        let result;
        try { result=JSON.parse(event.data); } catch { fail(state,'protocol_error');return; }
        if (result.type==='ready') {
          if(result.sample_rate!==16000 || result.frame_ms!==20 || typeof result.call_id!=='string') {clearTimeout(timer);reject(Error('Несовместимый аудиопротокол.'));fail(state,'protocol_error');return;}
          state.connected=true;state.callId=result.call_id;done();return;
        }
        if (result.type==='stopped') {
          state.finish?.(result.transcript_complete!==false);
          if (!state.finishing) { clearTimeout(timer);reject(Error('Сервер остановил звонок.'));fail(state,result.reason || 'server_stopped'); }
          return;
        }
        if (result.type==='balance') { notify('audio-balance',{sessionId:state.id,balance_ms:result.balance_ms}).catch(()=>fail(state,'runtime_lost'));return; }
        if (!['recognized','translation','interim'].includes(result.type) || !['incoming','outgoing'].includes(result.direction) ||
            !Number.isSafeInteger(result.sequence) || result.sequence<1) { fail(state,'protocol_error');return; }
        const direction=result.direction;
        const key=direction+':'+result.sequence;
        if(result.type==='interim'){
          notify('audio-live',{sessionId:state.id,event:result}).catch(()=>{});return;
        }
        if(result.type==='recognized'){
          state.recognizedAt.set(key,clockNow());
          if(state.recognizedAt.size>128)state.recognizedAt.delete(state.recognizedAt.keys().next().value);
        }
        state.journal=state.journal.then(()=>notify('audio-journal',{sessionId:state.id,event:result}));
        state.journal.catch(()=>fail(state,'journal_failed'));
        if (result.type==='recognized' || state.finishing) return;
        if (result.language!==(direction==='incoming'?state.source:state.target) || typeof result.text!=='string') { fail(state,'protocol_error');return; }
        if (result.sequence<=state.sequences[direction]) return;
        state.sequences[direction]=result.sequence;
        if (++state.counts[direction]>8) {fail(state,'translation_backlog');return;}
        const queued=clockNow();
        state.chains[direction]=state.chains[direction].then(async()=>{
          const timing={...result.timing,voice_queue_ms:Math.round(clockNow()-queued)};
          let first=true;
            for (const text of CTAudio.speechChunks(result.text)) {
            if (current!==state || !state.active) return;
            const began=clockNow();
            const response=await notify('native-synthesize',{sessionId:state.id,direction,text});
            if (!response?.audio) throw Error('Локальный компонент не вернул звук.');
            if (current!==state || !state.active) return;
            const ttsMs=Math.round(clockNow()-began);
            const playback=await localPlayback(state,response.audio,direction);
            if(first&&playback){
              Object.assign(timing,playback,{tts_ms:ttsMs});
                if(Number.isFinite(response.synthesis_ms)){
                  timing.synthesis_ms=response.synthesis_ms;
                  timing.native_transfer_ms=Math.max(0,ttsMs-response.synthesis_ms);
                }
              if(state.recognizedAt.has(key))timing.after_recognition_ms=Math.round(clockNow()-state.recognizedAt.get(key)+playback.playback_queue_ms);
              notify('audio-metrics',{sessionId:state.id,event:{type:'metrics',direction,sequence:result.sequence,timing}}).catch(()=>{});
              state.recognizedAt.delete(key);first=false;
            }
          }
        }).catch(()=>fail(state,'local_voice_failed')).finally(()=>state.counts[direction]--);
      };
    });
    state.capture=await CTpcm(state.context,state.stream,samples=>send(state,'incoming',samples),chrome.runtime.getURL('pcm-worklet.js'));
    state.heartbeat=setInterval(()=>notify('audio-heartbeat',{sessionId:state.id}).catch(()=>fail(state,'runtime_lost')),2000);
    return {call_id:state.callId};
  } catch (error) { await stop();throw error; }
}
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  if (message.target!=='offscreen' || sender.id!==chrome.runtime.id || sender.tab) return false;
  let task;
  if (message.type==='start') task=start(message);
  else if (!current || message.sessionId!==current.id) task=Promise.resolve({ignored:true});
  else if (message.type==='stop') task=stop();
  else if (message.type==='activate') {current.active=true;task=Promise.resolve();}
  else if (message.type==='pcm') {send(current,'outgoing',message.samples);task=Promise.resolve();}
  else if (message.type==='monitor') {current.hearOwn=message.enabled===true;task=protectPlayingAudio(current).then(()=>{for(const gain of current.monitors)gain.gain.value=current.hearOwn ? 0.55 : 0;});}
  else if (message.type==='echo-guard') {current.echoGuard=message.enabled===true;task=protectPlayingAudio(current);}
  else task=Promise.reject(Error('Неизвестный аудиозапрос.'));
  task.then(result=>respond({ok:true,...result}),()=>respond({error:'Аудиокомпонент не выполнил операцию.'}));
  return true;
});
