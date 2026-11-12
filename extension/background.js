'use strict';
importScripts('service-config.js','language-library.js', 'protocol.js', 'native-client.js', 'journal.js', 'transcript-format.js','transcript-files.js','call-controller.js');
chrome.storage.local.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'});
const localVoice = new LocalVoiceClient(chrome.runtime);
CTTranscriptFiles.configure(localVoice);

async function api(base, path, options = {}) {
  const response = await fetch(base + path, {...options, redirect: 'error', cache: 'no-store',signal:AbortSignal.timeout(15000)});
  if (!response.ok) throw Error(response.status === 401 ? 'Подключите аккаунт заново.' : 'Сервис временно недоступен.');
  return response.json();
}
const calls=new CTCallController(chrome,localVoice,CTJournal,api,CTTranscriptFiles);
const recovering=(async()=>{
  await calls.recover();
  // Snapshot recovery before accepting another call; file IO runs independently.
  const sessions=await CTJournal.sessions();
  CTTranscriptFiles.recover(sessions).catch(()=>{});
})().catch(()=>calls.publish('error','Не удалось восстановить предыдущий сеанс. Обновите вкладку Meet.'));

function nativeStatus() {
  return localVoice.request('status');
}

async function catalog() {
  const {service} = await chrome.storage.local.get('service');
  if (service !== CTService.url) throw Error('Сначала подключите аккаунт.');
  const status=await nativeStatus();
  if(!status.capabilities.includes('language-variants'))throw Error('Для полного списка языков обновите программу озвучки установщиком из кабинета.');
  return api(CTService.url, '/api/voices?scope=all');
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if(message.target==='offscreen' || sender.id!==chrome.runtime.id) return false;
  (async () => {
    await recovering;
    const viewer=sender.url===chrome.runtime.getURL('transcript.html');
    const popup=['popup.html','conversation.html'].some(file=>sender.url===chrome.runtime.getURL(file));
    if(!viewer && !popup) {
      if(sender.url===chrome.runtime.getURL('offscreen.html') || sender.tab && /^https:\/\/meet\.google\.com\//.test(sender.url || ''))
        return calls.event(message,sender);
      throw Error('Недопустимый источник запроса.');
    }
    if(['transcript-destination','transcript-folder-choose','transcript-folder-default','open-transcripts'].includes(message.type)){
      if(['transcript-folder-choose','transcript-folder-default'].includes(message.type)&&calls.run)throw Error('Завершите звонок перед изменением папки.');
      if(message.type==='transcript-destination')return CTTranscriptFiles.destination();
      if(message.type==='transcript-folder-choose'||message.type==='transcript-folder-default'){
        const folder=await (message.type==='transcript-folder-choose'?CTTranscriptFiles.choose():CTTranscriptFiles.defaults());
        const sessions=await CTJournal.sessions();CTTranscriptFiles.recover(sessions).catch(()=>{});
        return folder;
      }
      await CTTranscriptFiles.open();return {ok:true};
    }
    if(viewer) {
      if(message.type==='journal-sessions') return CTJournal.sessions();
      if(message.type==='journal-entries') return CTJournal.entries(message.session);
      if(message.type==='journal-save'){
        const session=(await CTJournal.sessions()).find(item=>item.id===message.session);
        if(!session)throw Error('Разговор не найден.');
        await CTTranscriptFiles.exportSession(session,{force:true});return {saved:true};
      }
      throw Error('Недопустимый запрос стенограммы.');
    }
    if(!popup) throw Error('Недопустимый источник запроса.');
    if(message.type==='call-state') return calls.status();
    if(message.type==='conversation-state')return (await chrome.storage.session.get('liveConversation')).liveConversation||calls.live;
    if(message.type==='call-start') return calls.start(message);
    if(message.type==='call-stop') return calls.stop();
    if(message.type==='call-monitor') {
      await chrome.storage.local.set({hearOwnTranslation:message.enabled===true});
      if(calls.run && !calls.run.cancelled) await calls.offscreen(calls.run,'monitor',{enabled:message.enabled===true});
      return {ok:true};
    }
    if(message.type==='call-echo-guard') {
      await chrome.storage.local.set({echoGuard:message.enabled===true});
      if(calls.run && !calls.run.cancelled){
        await calls.page(calls.run,'guardMode',message.enabled===true);
        await calls.offscreen(calls.run,'echo-guard',{enabled:message.enabled===true});
      }
      return {ok:true};
    }
    if(message.type==='open-conversation'){await chrome.windows.create({url:chrome.runtime.getURL('conversation.html'),type:'popup',width:1000,height:800});return {ok:true};}
    if (message.type === 'state') {
      const {service, credential} = await chrome.storage.local.get(['service', 'credential']);
      if (service !== CTService.url || !credential) return {connected: false};
      const account = await api(CTService.url, '/api/account', {headers: {Authorization: 'Bearer '+credential}});
      return {connected: true, balance_ms: account.balance_ms, active_call: Boolean(account.active_call)};
    }
    if (message.type === 'pair') {
      const service = CTService.url;
      if (typeof message.code !== 'string' || !/^[A-Za-z0-9_-]{40,128}$/.test(message.code)) throw Error('Вставьте полный одноразовый код из кабинета.');
      const result = await api(service, '/api/devices/redeem', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: message.code})});
      await chrome.storage.local.set({service, credential: result.access_token, device: result.device_id});
      return {connected: true};
    }
    if (message.type === 'unlink') {
      await calls.stop('device_unlinked');
      const {service, credential} = await chrome.storage.local.get(['service', 'credential']);
      if (service === CTService.url && credential) await api(CTService.url, '/api/devices/unlink',
        {method: 'POST', headers: {Authorization: 'Bearer '+credential}});
      await chrome.storage.local.remove(['service', 'credential', 'device']);
      return {connected: false};
    }
    if (message.type === 'native-status') return nativeStatus();
    if (message.type === 'voice-catalog') return localVoice.request('catalog-info', {catalog: await catalog()});
    if (['voice-install', 'voice-preview', 'voice-select', 'voice-remove'].includes(message.type)) {
      if(calls.run) throw Error('Завершите звонок перед изменением голосов.');
      if (typeof message.voice_id !== 'string' || !/^[a-z][a-z0-9-]{0,63}$/.test(message.voice_id)) throw Error('Некорректный голос.');
      if (message.type === 'voice-install') return localVoice.request('install-voice', {catalog: await catalog(), voice_id: message.voice_id});
      if (message.type === 'voice-preview') return localVoice.request('preview-voice', {voice_id: message.voice_id});
      if (message.type === 'voice-remove') return localVoice.request('remove-voice',{voice_id:message.voice_id});
      if (!['incoming','outgoing'].includes(message.direction)) throw Error('Некорректное направление.');
      return localVoice.request('select-voice', {voice_id: message.voice_id, direction: message.direction});
    }
    throw Error('Неизвестный запрос.');
  })().then(result => respond({ok: true, result}), error => respond({ok: false, error: error.message}));
  return true;
});
chrome.tabs.onRemoved.addListener(tabId=>{if(calls.run?.tabId===tabId) calls.stop('tab_closed').catch(()=>{});});
chrome.tabs.onUpdated.addListener((tabId,change)=>{if(calls.run?.tabId===tabId && change.status==='loading') calls.stop('tab_navigation').catch(()=>{});});
