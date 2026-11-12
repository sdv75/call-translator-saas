importScripts('native-client.js');
importScripts('transcript-store.js');
importScripts('transcript-format.js');
let conversation = null;
let latestSpeech = {};
const nativePiper = new NativePiperClient(chrome.runtime);
let activeTab = null, session = 0;
let journalWrites = Promise.resolve(), stopping = null;
let runState = {phase: 'stopped', text: 'Перевод выключен. Войдите в Meet и нажмите «Включить перевод».'};
async function setRunState(phase, text) {
  runState = {phase, text, tabId: activeTab, updated_at: Date.now()};
  await chrome.storage.local.set({translationState: runState, status: text});
}
async function beginConversation(source, target) {
  conversation = crypto.randomUUID(); latestSpeech = {};
  await CTjournal.saveSession({id: conversation, started_at: Date.now(), source, target, state: 'active'});
  await chrome.storage.local.set({currentConversation: conversation, activeConversation: conversation});
  await chrome.storage.local.remove(['speech0', 'speech1']);
  await chrome.storage.local.remove('transcriptError');
  return conversation;
}
async function exportConversation(id, automatic = false) {
  await journalWrites;
  const info = await CTjournal.session(id);
  if (!info) throw Error('Беседа не найдена.');
  if (automatic && Number.isInteger(info.download_id)) return info.download_id;
  const events = await CTjournal.entries(id);
  const downloadId = await chrome.downloads.download({
    url: 'data:text/html;charset=utf-8,' + encodeURIComponent(CTtranscript.html(info, events)),
    filename: CTtranscript.filename(info), saveAs: false, conflictAction: 'uniquify'
  });
  await CTjournal.saveSession({...info, download_id: downloadId, exported_at: Date.now()});
  await chrome.storage.local.set({lastTranscriptFile: CTtranscript.filename(info)});
  await chrome.storage.local.remove('transcriptError');
  return downloadId;
}
async function finishConversation(id) {
  if (!id) return;
  await journalWrites;
  const info = await CTjournal.session(id);
  if (!info) return;
  await CTjournal.saveSession({...info, ended_at: info.ended_at || Date.now(), state: 'closed'});
  await exportConversation(id, true);
}
async function recordJournalEntry(entry) {
  const id = entry.conversation || conversation;
  const write = journalWrites.then(async () => {
  await CTjournal.put({...entry, conversation: id, id: `${id}:${entry.direction}:${entry.sequence}`});
  const previous = latestSpeech[entry.direction];
  if (id === conversation && (!previous || entry.sequence >= previous.sequence)) {
    latestSpeech[entry.direction] = entry;
    await chrome.storage.local.set({['speech' + entry.direction]: entry});
  }
  return {ok: true};
  });
  journalWrites = write.catch(() => {});
  return write;
}
nativePiper.onLost = () => {
  if (activeTab !== null) stop().then(() => setRunState('error', 'Локальный Piper отключился. Перевод остановлен. Включите перевод повторно.')).catch(() => {});
};
async function page(method, payload) {
  if (activeTab === null) return;
  const results = await chrome.scripting.executeScript({target: {tabId: activeTab}, world: 'MAIN',
    func: async (method, payload) => {
      try { if (!window.__CTtranslate) throw Error('Обновите вкладку Meet.');
        await window.__CTtranslate[method](payload); return {ok: true};
      } catch (error) { return {error: error.message}; }
    }, args: [method, payload ?? null]});
  if (results[0]?.result?.error) throw Error(results[0].result.error);
  if (!results[0]?.result?.ok) throw Error('Нет подтверждения запуска во вкладке Meet. Обновите вкладку.');
}
async function stop(keepNative = false) {
  if (stopping) return stopping;
  stopping = finishStop(keepNative);
  try { return await stopping; } finally { stopping = null; }
}
async function finishStop(keepNative) {
  const old = conversation || (await chrome.storage.local.get('activeConversation')).activeConversation;
  const wasActive = old || activeTab !== null;
  if (wasActive) await setRunState('stopping', 'Завершаю распознавание и сохраняю стенограмму…');
  session++;
  await page('stop').catch(() => {});
  if (await chrome.offscreen.hasDocument()) {
    const finished = await chrome.runtime.sendMessage({target: 'offscreen', type: 'stop'}).catch(() => null);
    if (old && finished?.complete === false) {
      const info = await CTjournal.session(old);
      if (info) await CTjournal.saveSession({...info, finish_warning: 'Связь прервана: последние фрагменты могли не завершить распознавание или перевод.'});
    }
    await chrome.offscreen.closeDocument();
  }
  activeTab = null;
  if (!keepNative) nativePiper.close();
  await journalWrites;
  if (conversation === old) conversation = null;
  await chrome.storage.local.remove('activeConversation');
  try {
    await finishConversation(old);
    if (wasActive) await setRunState('stopped', old ? 'Беседа завершена. Стенограмма сохранена в Загрузки / CallTranslator.' : 'Перевод выключен.');
  }
  catch (error) {
    await chrome.storage.local.set({transcriptError: 'Не удалось автоматически сохранить HTML: ' + error.message});
  }
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.target === 'offscreen') return;
  const run = async () => {
    if (message.type === 'get-state') return {ok: true, ...runState};
    if (message.type === 'start' && !sender.tab) {
      await stop(message.tts === 'client' && activeTab === null); activeTab = message.tabId;
      const started = session;
      try {
        await setRunState('connecting', 'Проверяю связь со вкладкой Meet…');
        let bridge;
        try { bridge = await chrome.tabs.sendMessage(activeTab, {type: 'bridge-ready'}); }
        catch (_) { throw Error('Обновите вкладку Meet после обновления расширения и войдите в звонок заново.'); }
        if (!bridge?.ok) throw Error('Связь с расширением потеряна. Обновите вкладку Meet.');
        if (session !== started) return {cancelled: true};
        await beginConversation(message.source, message.language);
        if (session !== started) return {cancelled: true};
        // The background owns startup. Closing the popup must not cancel voice loading.
        const preparing = message.tts === 'client'
          ? nativePiper.init().then(ready => ({ready}), error => ({error})) : null;
        await setRunState('connecting', 'Подключаю звук вкладки и сервер перевода…');
        await chrome.offscreen.createDocument({url: 'offscreen.html', reasons: ['USER_MEDIA'], justification: 'Двусторонний перевод аудио выбранной вкладки Meet'});
        const result = await chrome.runtime.sendMessage({...message, conversation, target: 'offscreen'});
        if (session !== started) return {cancelled: true};
        if (result?.error) throw Error(result.error);
        if (!result?.ok) throw Error('Нет подтверждения подключения звука и сервера. Повторите запуск.');
        await setRunState('starting', 'Подключаю микрофон Meet…');
        await page('start', {workletURL: chrome.runtime.getURL('pcm-worklet.js'), hearOwnTranslation: message.hearOwnTranslation === true, echoGuard: message.echoGuard === true});
        if (preparing) {
          await setRunState('preparing', 'Загружаю локальные голоса Piper. Первый запуск может занять до 90 секунд…');
          const {ready, error} = await preparing;
          if (session !== started) return {cancelled: true};
          if (error) throw error;
          if (![message.source, message.language].every(language => ready.voices.includes(language)))
            throw Error('Обновите локальный компонент Piper: выбранный голос не установлен.');
        }
        if (session !== started) return {cancelled: true};
        await setRunState('running', 'Перевод включён. Говорите — распознанные слова появятся ниже.');
        return {ok: true};
      } catch (error) {
        if (session !== started) return {cancelled: true};
        await stop(); await setRunState('error', error.message); throw error;
      }
    }
    if (['native-check', 'native-prepare'].includes(message.type) && !sender.tab && sender.url === chrome.runtime.getURL('popup.html')) {
      if (message.type === 'native-prepare' && activeTab !== null) await stop();
      const ready = await nativePiper.init();
      return {ok: true, voices: ready.voices};
    }
    if (message.type === 'native-synthesize' && !sender.tab && sender.url === chrome.runtime.getURL('offscreen.html') && activeTab !== null) {
      const rendering = session;
      const started = performance.now();
      const result = await nativePiper.synthesize(message.text, message.language);
      if (session !== rendering) throw Error('Перевод остановлен.');
      return {...result, elapsedMs: performance.now() - started};
    }
    if (message.type === 'pcm' && sender.tab?.id === activeTab) {
      return chrome.runtime.sendMessage({target: 'offscreen', type: 'pcm', samples: message.samples});
    }
    if (message.type === 'page-failed' && sender.tab?.id === activeTab) {
      await stop();
      await setRunState('error', 'Meet сменил аудиодорожку. Перевод остановлен, включён обычный микрофон. Включите перевод повторно.');
      return;
    }
    if (message.type === 'translated-audio' && !sender.tab) return page('audio', {audio: message.audio, ownTranslation: message.ownTranslation === true});
    if (message.type === 'export-conversation' && sender.url?.split('?')[0] === chrome.runtime.getURL('transcript.html')) {
      return {ok: true, downloadId: await exportConversation(message.conversation)};
    }
    if (message.type === 'journal' && !sender.tab && sender.url === chrome.runtime.getURL('offscreen.html')) {
      return recordJournalEntry(message.entry);
    }
    if (message.type === 'translation-status' && !sender.tab &&
        sender.url === chrome.runtime.getURL('offscreen.html') && typeof message.text === 'string') {
      const timing = Number.isFinite(message.latencyMs) ? ` (обработка: ${(message.latencyMs / 1000).toFixed(1)} с)` : '';
      const phases = message.timingsMs;
      const details = phases && ['queue', 'translation', 'tts'].every(key => Number.isFinite(phases[key]))
        ? `; очередь ${(phases.queue / 1000).toFixed(1)} с, перевод ${(phases.translation / 1000).toFixed(1)} с, голос ${(phases.tts / 1000).toFixed(1)} с` : '';
      const original = typeof message.original === 'string' ? `Распознано: «${message.original}» → ` : '';
      await chrome.storage.local.set({lastProcessing: original + message.text + timing + details});
      return;
    }
    if (message.type === 'failed' && !sender.tab) {
      await stop(); await setRunState('error', message.error); return;
    }
    if (message.type === 'stop' && !sender.tab || message.type === 'tab-ended' && sender.tab?.id === activeTab) return stop();
  };
  run().then(result => respond(result || {ok: true})).catch(error => respond({error: error.message}));
  return true;
});
chrome.tabs.onRemoved.addListener(tabId => { if (tabId === activeTab) stop(); });
chrome.runtime.onStartup.addListener(() => { stop().catch(() => {}); });
chrome.runtime.onInstalled.addListener(() => { stop().catch(() => {}); });
chrome.downloads.onChanged.addListener(async delta => {
  if (!['complete', 'interrupted'].includes(delta.state?.current)) return;
  try {
    const info = (await CTjournal.conversations()).find(session => session.download_id === delta.id);
    if (!info) return;
    if (delta.state.current === 'interrupted') {
      await CTjournal.saveSession({...info, download_id: null, export_error: delta.error?.current || 'Загрузка прервана'});
      await chrome.storage.local.set({transcriptError: 'HTML не сохранился. Журнал беседы доступен в расширении; повторите сохранение выбранной беседы.'});
    } else {
      const [download] = await chrome.downloads.search({id: delta.id});
      await CTjournal.saveSession({...info, export_file: download?.filename, export_complete: true});
      await chrome.storage.local.set({lastTranscriptFile: download?.filename || CTtranscript.filename(info)});
    }
  } catch (_) {}
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.hearOwnTranslation && activeTab !== null)
    page('monitor', changes.hearOwnTranslation.newValue === true).catch(() => {});
});