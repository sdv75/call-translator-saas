async function command(action) {
  const status = document.getElementById('status');
  try {
    await chrome.runtime.sendMessage({type: 'stop'});
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (!tab?.url?.startsWith('https://meet.google.com/')) throw Error('Откройте Google Meet.');
    let sample = null;
    if (action === 'mount') {
      const response = await fetch(chrome.runtime.getURL('probe.wav'));
      if (!response.ok) throw Error('Не найдена тестовая запись речи.');
      const data = new Uint8Array(await response.arrayBuffer());
      let binary = '';
      for (const byte of data) binary += String.fromCharCode(byte);
      sample = btoa(binary);
    }
    const results = await chrome.scripting.executeScript({
      target: {tabId: tab.id}, world: 'MAIN',
      func: async (action, sample) => {
        const bridge = window.__callTranslatorProbe;
        if (!bridge) return 'Обновите вкладку Meet после установки расширения.';
        try { return await bridge[action](sample); } catch (error) { return String(error.message); }
      }, args: [action, sample]
    });
    status.textContent = results[0]?.result || 'Нет ответа от Meet.';
  } catch (error) { status.textContent = error.message; }
}
document.getElementById('probe').onclick = () => command('mount');
document.getElementById('restore').onclick = () => command('restore');
document.getElementById('browser-tts').onclick = () => chrome.tabs.create({url: chrome.runtime.getURL('tts-test.html')});
const status = document.getElementById('status');
let starting = false;
let visibleState = {phase: 'stopped', text: 'Войдите в Meet и нажмите «Включить перевод».'};
function showState(state) {
  visibleState = state;
  const labels = {stopped: 'Перевод выключен', connecting: 'Подключение…', starting: 'Подключение микрофона…',
    preparing: 'Загрузка голосов Piper…', running: 'Перевод включён', stopping: 'Завершение беседы…', error: 'Перевод не работает'};
  const banner = document.getElementById('run-state');
  banner.textContent = labels[state.phase] || 'Перевод выключен'; banner.dataset.phase = state.phase;
  if (state.text) status.textContent = state.text;
  const busy = ['connecting', 'starting', 'preparing', 'running', 'stopping'].includes(state.phase);
  document.getElementById('start').disabled = starting || busy;
  document.getElementById('stop').disabled = !busy || state.phase === 'stopping';
}
async function refreshState() {
  const state = await chrome.runtime.sendMessage({type: 'get-state'});
  if (!state?.ok) throw Error(state?.error || 'Нет связи с расширением. Обновите его в chrome://extensions.');
  showState(state);
}
function showSpeech(direction, entry) {
  const who = direction === 0 ? 'Вы' : 'Собеседник';
  const element = document.getElementById('speech' + direction);
  if (!entry) { element.textContent = who + ': ожидаю речь.'; return; }
  const note = entry.uncertain ? ' [распознано неуверенно]' : '';
  const progress = entry.partial ? ' [фраза продолжается]' : '';
  element.textContent = `${who}${note}${progress}: ${entry.text} → ${entry.translation || 'перевод ожидается…'}`;
}
chrome.storage.local.get(['source', 'language', 'tts', 'status', 'speech0', 'speech1', 'hearOwnTranslation']).then(saved => {
  for (const key of ['source', 'language', 'tts']) if (saved[key]) document.getElementById(key).value = saved[key];
  document.getElementById('hearOwnTranslation').checked = saved.hearOwnTranslation === true;
  for (const direction of [0, 1]) showSpeech(direction, saved['speech' + direction]);
});
refreshState().catch(error => showState({phase: 'error', text: error.message}));
document.getElementById('start').onclick = async () => {
  starting = true; showState({phase: 'connecting', text: 'Проверяю вкладку Meet…'});
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (!tab?.url?.startsWith('https://meet.google.com/')) throw Error('Откройте вкладку Meet.');
    const source = document.getElementById('source').value, language = document.getElementById('language').value;
    if (source === language) throw Error('Выберите разные языки.');
    const tts = document.getElementById('tts').value;
    if (tts !== 'client' && [source, language].includes('uk'))
      throw Error('Для украинского языка выберите «На компьютере (Piper)».');
    const streamId = await chrome.tabCapture.getMediaStreamId({targetTabId: tab.id});
    status.textContent = 'Подключение…';
    await chrome.storage.local.set({source, language, tts});
    const echoGuard = document.getElementById('echoGuard').checked;
    const result = await chrome.runtime.sendMessage({type: 'start', tabId: tab.id, streamId, source, language, tts, echoGuard, hearOwnTranslation: document.getElementById('hearOwnTranslation').checked});
    if (result?.cancelled) { await refreshState(); return; }
    if (result?.error) throw Error(result.error);
    if (!result?.ok) throw Error('Нет подтверждения запуска перевода. Повторите запуск.');
    await refreshState();
  } catch (error) {
    showState({phase: 'error', text: error.message});
    await chrome.storage.local.set({status: error.message});
  }
  finally { starting = false; showState(visibleState); }
};
document.getElementById('native-check').onclick = async () => {
  const button = document.getElementById('native-check'); button.disabled = true;
  status.textContent = 'Подключение локального Piper и загрузка голосов…';
  try {
    const result = await chrome.runtime.sendMessage({type: 'native-check'});
    if (!result?.ok) throw Error(result?.error || 'Нет ответа от локального Piper.');
    status.textContent = 'Локальный Piper готов. Языки: ' + result.voices.join(', ') + '.';
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
};
document.getElementById('stop').onclick = async () => {
  const button = document.getElementById('stop'); button.disabled = true;
  showState({phase: 'stopping', text: 'Завершаю распознавание и сохраняю стенограмму…'});
  try {
    const result = await chrome.runtime.sendMessage({type: 'stop'});
    if (result?.error) throw Error(result.error);
    const saved = await chrome.storage.local.get(['transcriptError', 'lastTranscriptFile']);
    const text = saved.transcriptError || ('Перевод остановлен.' + (saved.lastTranscriptFile ? ' Стенограмма: ' + saved.lastTranscriptFile : ''));
    await chrome.storage.local.set({status: text}); await refreshState(); status.textContent = text;
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
};
chrome.storage.onChanged.addListener(changes => {
  if (changes.translationState) showState(changes.translationState.newValue);
  else if (changes.status) status.textContent = changes.status.newValue;
  for (const direction of [0, 1]) if (changes['speech' + direction]) showSpeech(direction, changes['speech' + direction].newValue);
});
document.getElementById('transcript').onclick = () => chrome.tabs.create({url: chrome.runtime.getURL('transcript.html')});

document.getElementById('hearOwnTranslation').onchange = async event => {
  try {
    await chrome.storage.local.set({hearOwnTranslation: event.target.checked});
  } catch (error) { status.textContent = error.message; }
};