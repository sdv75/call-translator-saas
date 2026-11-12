import {VOICES, report, summaries} from './tts-test-common.mjs';

const $ = id => document.getElementById(id);
let worker, nextId = 0, busy = false, generation = 0, audioUrl;
const pending = new Map(), rows = [], downloads = [];
const environment = {userAgent: navigator.userAgent, hardwareConcurrency: navigator.hardwareConcurrency,
  deviceMemoryGB: navigator.deviceMemory, extensionVersion: chrome.runtime.getManifest().version};
function status(text, error = false) { $('status').textContent = text; $('status').classList.toggle('error', error); }
function stopAudio() { $('audio').pause(); $('audio').currentTime = 0; }
function resetWorker(reason = 'Операция отменена.') {
  generation++;
  worker?.terminate(); worker = null;
  for (const request of pending.values()) { clearTimeout(request.timer); request.reject(Error(reason)); }
  pending.clear();
}
function request(action, language, text) {
  if (!worker) {
    worker = new Worker(chrome.runtime.getURL('tts-test-worker.js'), {type: 'module'});
    worker.onmessage = ({data}) => {
      const request = pending.get(data.id);
      if (!request) return;
      if (data.progress) {
        const {loaded, total} = data.progress;
        $('progress').hidden = false;
        if (total) { $('progress').max = total; $('progress').value = loaded; }
        else $('progress').removeAttribute('value');
        status(`Загрузка голоса: ${(loaded / 1048576).toFixed(1)} МБ${total ? ` из ${(total / 1048576).toFixed(1)} МБ` : ''}…`);
        return;
      }
      clearTimeout(request.timer); pending.delete(data.id);
      data.error ? request.reject(Error(data.error)) : request.resolve(data.result);
    };
    worker.onerror = event => {
      event.preventDefault();
      resetWorker(`Не удалось запустить браузерный Piper: ${event.message || 'ошибка worker или CSP'}`);
    };
  }
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    // Downloads can be slow; the user can cancel at any moment.
    const timer = setTimeout(() => resetWorker('Операция превысила 10 минут. Повторите попытку.'), 600000);
    pending.set(id, {resolve, reject, timer});
    worker.postMessage({id, action, language, text});
  });
}
function setBusy(value) {
  busy = value;
  for (const id of ['language', 'text', 'download', 'remove', 'short', 'long', 'synthesize', 'benchmark', 'clear']) $(id).disabled = value;
  $('cancel').disabled = !value;
  if (!value) $('progress').hidden = true;
}
async function refresh() {
  const cached = await request('stored');
  $('cache').textContent = Object.entries(VOICES).map(([language, voice]) =>
    `${voice.label}: ${cached[language] ? 'сохранён на компьютере' : 'ещё не скачан'}`).join(' · ');
  return cached;
}
async function operation(fn) {
  if (busy) return;
  setBusy(true);
  try { await fn(); }
  catch (error) { status(error.message, true); }
  finally { setBusy(false); }
}
function table() {
  $('results').replaceChildren();
  for (const row of rows) {
    const tr = document.createElement('tr');
    const mode = `${row.benchmark ? (row.kind === 'long' ? 'Длинная' : 'Короткая') : 'Своя фраза'} · ${row.cold ? 'первый запуск' : 'повторный'}`;
    for (const value of [VOICES[row.language].label, mode, (row.prepareMs / 1000).toFixed(2),
      (row.synthesisMs / 1000).toFixed(2), row.audioSeconds.toFixed(2), row.ratio.toFixed(3)]) {
      const cell = document.createElement('td'); cell.textContent = value; tr.append(cell);
    }
    $('results').append(tr);
  }
  const groups = summaries(rows);
  $('summary').textContent = groups.every(group => group.count >= 5)
    ? (groups.every(group => group.pass) ? 'По скорости проверка пройдена для обоих языков.' : 'По скорости проверка пройдена не для всех фраз. Скопируйте отчёт для разбора.')
    : 'Для итоговой оценки запустите полную проверку обоих языков.';
}
async function download(language) {
  status(`Подготовка загрузки: ${VOICES[language].label}…`);
  const result = await request('download', language);
  downloads.push({language, ...result});
  await refresh();
  return result;
}
async function synthesize(language, text, kind = 'custom', benchmark = false) {
  status(`Синтез: ${VOICES[language].label}…`);
  const result = await request('synthesize', language, text);
  rows.push({language, voice: VOICES[language].id, kind, benchmark,
    prepareMs: result.prepareMs, synthesisMs: result.synthesisMs, cold: result.cold,
    audioSeconds: result.audioSeconds, ratio: result.ratio});
  table();
  stopAudio();
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = URL.createObjectURL(new Blob([result.wav], {type: 'audio/wav'}));
  $('audio').src = audioUrl; $('audio').hidden = false;
  return result;
}
$('language').onchange = () => { $('text').value = VOICES[$('language').value].short; };
$('short').onclick = () => { $('text').value = VOICES[$('language').value].short; };
$('long').onclick = () => { $('text').value = VOICES[$('language').value].long; };
$('download').onclick = () => operation(async () => {
  const result = await download($('language').value);
  status(result.cached ? 'Голос уже сохранён. Можно создать озвучку.' : `Голос скачан за ${(result.ms / 1000).toFixed(1)} с. Можно создать озвучку.`);
});
$('remove').onclick = () => operation(async () => {
  stopAudio(); resetWorker();
  await request('remove', $('language').value); await refresh(); status('Выбранный голос удалён.');
});
$('synthesize').onclick = () => operation(async () => {
  const text = $('text').value.trim();
  if (!text) throw Error('Введите текст для озвучивания.');
  const result = await synthesize($('language').value, text);
  status(`Готово. Синтез: ${(result.synthesisMs / 1000).toFixed(2)} с; речь: ${result.audioSeconds.toFixed(2)} с. Нажмите ▶ для прослушивания.`);
});
$('cancel').onclick = () => { stopAudio(); resetWorker(); status('Операция отменена. Неполная загрузка не считается сохранённым голосом.'); };
$('stop-audio').onclick = stopAudio;
$('benchmark').onclick = () => operation(async () => {
  stopAudio(); resetWorker();
  const run = generation;
  // A fresh run must not mix previous warm measurements into the verdict.
  rows.length = 0; table();
  for (const language of ['ru', 'en']) {
    await download(language);
    if (generation !== run) throw Error('Проверка отменена.');
    await synthesize(language, VOICES[language].short, 'short', true); // cold run excluded from verdict
    for (const kind of ['short', 'long']) {
      for (let i = 0; i < 5; i++) {
        if (generation !== run) throw Error('Проверка отменена.');
        await synthesize(language, VOICES[language][kind], kind, true);
      }
    }
  }
  status('Проверка завершена. Прослушайте последнюю фразу и скопируйте технический отчёт.');
});
$('copy').onclick = async () => {
  try { await navigator.clipboard.writeText(JSON.stringify(report(rows, downloads, environment), null, 2)); status('Технический отчёт скопирован. Текст фраз в него не включён.'); }
  catch { status('Chrome не разрешил копирование. Повторите нажатие кнопки в активной вкладке.', true); }
};
$('clear').onclick = () => { rows.length = 0; downloads.length = 0; table(); status('Замеры очищены.'); };
window.addEventListener('pagehide', () => { resetWorker(); stopAudio(); if (audioUrl) URL.revokeObjectURL(audioUrl); });
$('text').value = VOICES.ru.short;
table();
operation(async () => {
  if (!navigator.storage?.getDirectory || typeof WebAssembly !== 'object') throw Error('В этом Chrome недоступны OPFS или WebAssembly. Обновите браузер.');
  await refresh(); status('Выберите язык и скачайте голос. Затем создайте озвучку или запустите полную проверку.');
});
