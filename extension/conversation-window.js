'use strict';
const el=id=>document.getElementById(id);
async function request(type){const reply=await chrome.runtime.sendMessage({type});if(!reply?.ok)throw Error(reply?.error||'Расширение не ответило.');return reply.result;}
function status(state){
  if(!state)return;
  el('call-panel').dataset.phase=state.phase;el('call-state').textContent=state.text;
  el('call-heading').textContent=({active:'Перевод работает',starting:'Подготовка…',stopping:'Остановка…',error:'Перевод остановлен: ошибка',stopped:'Перевод выключен'})[state.phase]||'Состояние перевода';
  el('call-stop').disabled=!['starting','active'].includes(state.phase);
  el('transcript-folder').disabled=['starting','active','stopping'].includes(state.phase);
  el('call-error-code').hidden=!state.code;el('call-error-code').textContent=state.code?'Код ошибки: '+state.code:'';
}
el('call-stop').addEventListener('click',async()=>{el('call-stop').disabled=true;try{status(await request('call-stop'));}catch(error){status({phase:'error',text:error.message});}});
el('transcripts').addEventListener('click',()=>request('open-transcripts').catch(error=>status({phase:'error',text:error.message})));
el('transcript-folder').addEventListener('click',async()=>{try{const folder=await request('transcript-folder-choose');el('transcript-path').textContent=folder.name;}catch(error){status({phase:'error',text:error.message});}});
request('transcript-destination').then(folder=>{el('transcript-path').textContent=folder.name;el('transcript-path').title=folder.path;}).catch(()=>{});
el('export-metrics').addEventListener('click',CTConversation.exportMetrics);
chrome.storage.onChanged.addListener((changes,area)=>{if(area!=='session')return;if(changes.callStatus)status(changes.callStatus.newValue);if(changes.liveConversation)CTConversation.render(changes.liveConversation.newValue);});
Promise.all([request('call-state').then(status),request('conversation-state').then(CTConversation.render)]).catch(error=>status({phase:'error',text:error.message}));
