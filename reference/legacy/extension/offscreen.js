let state = null;
function b64(bytes) { let text = ''; for (const byte of bytes) text += String.fromCharCode(byte); return btoa(text); }
function speechChunks(text, limit = 1400) {
  const chunks = [];
  while (text.length > limit) {
    let end = text.lastIndexOf(' ', limit);
    if (end < limit / 2) end = limit;
    if (/[\uD800-\uDBFF]/.test(text[end - 1])) end--;
    chunks.push(text.slice(0, end)); text = text.slice(end);
  }
  if (text) chunks.push(text);
  return chunks;
}
function send(direction, samples) {
  if (!state?.ready || state.ws.readyState !== WebSocket.OPEN) return;
  // WebSocket buffers frames in order; never silently discard congested PCM.
  if (state.ws.bufferedAmount > 19200000) {
    chrome.runtime.sendMessage({type: 'failed', error: 'Сеть не успевает передавать речь: накоплено более 5 минут аудио. Перевод остановлен; сохранённая стенограмма доступна.'});
    state.ready = false; return;
  }
  const packet = new ArrayBuffer(641), view = new DataView(packet); view.setUint8(0, direction);
  for (let i = 0; i < 320; i++) view.setInt16(1+i*2, samples[i], true);
  state.ws.send(packet);
}
async function stop() {
  const old = state;
  if (!old) return;
  const wasReady = old.ready; old.ready = false; old.finishing = true;
  old.capture?.(); old.stream?.getTracks().forEach(track => track.stop());
  let complete = false;
  if (wasReady && old.canFinish && old.ws?.readyState === WebSocket.OPEN) {
    complete = await new Promise(resolve => {
      const timer = setTimeout(() => resolve(false), 50000);
      old.finishResolve = value => { clearTimeout(timer); resolve(value); };
      old.ws.send(JSON.stringify({type: 'stop'}));
    });
  }
  await old.journal;
  if (state === old) state = null;
  old.ws?.close(); if (old.context) await old.context.close();
  return {complete};
}
async function playShared(current, audio, direction) {
  // Both listeners receive the same WAV; monitor outside the captured Meet tab.
  const buffer = await current.context.decodeAudioData(audio.slice(0));
  if (state !== current || current.finishing) return;
  const response = await chrome.runtime.sendMessage({type: 'translated-audio', audio: b64(new Uint8Array(audio)), ownTranslation: direction === 1});
  if (response?.error) throw Error(response.error);
  if (state !== current || current.finishing) return;
  const source = current.context.createBufferSource(); source.buffer = buffer;
  const gain = current.context.createGain(); gain.gain.value = direction === 0 && !current.hearOwnTranslation ? 0 : 0.55;
  if (direction === 0) current.monitors.add(gain);
  source.connect(gain); gain.connect(current.context.destination);
  source.onended = () => { source.disconnect(); gain.disconnect(); current.monitors.delete(gain); };
  const when = Math.max(current.context.currentTime, current.next);
  current.next = when + buffer.duration; source.start(when);
}
function playIncoming(current, audio, direction) {
  const task = current.playback.then(() => playShared(current, audio, direction));
  current.playback = task.catch(() => {});
  return task;
}
async function start(message) {
  await stop();
  const config = await (await fetch(chrome.runtime.getURL('connection.json'))).json();
  const current = {hearOwnTranslation: message.hearOwnTranslation === true, monitors: new Set(), ready: false, next: 0, playback: Promise.resolve(), sequences: [0, 0], audioResults: [[], []], journal: Promise.resolve(true), chains: [Promise.resolve(), Promise.resolve()]}; state = current;
  try {
    current.stream = await navigator.mediaDevices.getUserMedia({audio: {mandatory: {
      chromeMediaSource: 'tab', chromeMediaSourceId: message.streamId}}, video: false});
    current.stream.getTracks().forEach(track => track.addEventListener('ended', () => {
      if (state === current && !current.finishing) chrome.runtime.sendMessage({type: 'failed', error: 'Захват вкладки завершён. Включите перевод повторно.'});
    }));
    current.context = new AudioContext(); await current.context.resume();
    current.ws = new WebSocket('wss://ppsbot.pp.ua/call-translator/ws-extension');
    current.ws.binaryType = 'arraybuffer';
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('Сервер не ответил за 30 секунд')), 30000);
      current.ws.onopen = () => current.ws.send(JSON.stringify({type: 'auth', token: config.token}));
      current.ws.onerror = () => { clearTimeout(timer); reject(Error('Не удалось подключиться к серверу')); };
      current.ws.onclose = () => {
        clearTimeout(timer); reject(Error('Сервер закрыл соединение'));
        current.finishResolve?.(false);
        if (state === current && !current.finishing) chrome.runtime.sendMessage({type: 'failed', error: 'Соединение прервано. Нажмите «Включить перевод» повторно.'});
      };
      const handle = async event => {
        if (state !== current) return;
        try {
          if (typeof event.data === 'string') {
            const result = JSON.parse(event.data);
            if (result.type === 'authenticated') current.ws.send(JSON.stringify({type: 'start', protocol: 1, source: message.source, target: message.language, tts: message.tts || 'server'}));
            if (result.type === 'error') throw Error('Ошибка обработки речи на сервере');
            if (result.type === 'finished') { current.finishResolve?.(true); return; }
            if (result.type === 'ready') {
              if (message.tts === 'client' && result.tts !== 'client') throw Error('Сервер не поддерживает локальную озвучку. Обновите сервер или выберите озвучку на сервере.');
              current.canFinish = result.graceful_stop === true;
              current.ready = true; clearTimeout(timer); resolve();
            }
            if (result.type === 'translation') {
              const direction = result.direction;
              if ((direction === 0 || direction === 1) && Number.isInteger(result.sequence)) {
                const fresh = result.sequence > current.sequences[direction];
                if (message.tts !== 'client') current.audioResults[direction].push(fresh);
                if (!fresh) return;
                current.sequences[direction] = result.sequence;
              }
              let native;
              if (current.finishing) return; // Text is journaled independently; no new speech after Stop.
              if (message.tts === 'client') {
                const expected = direction === 0 ? message.language : message.source;
                if (result.tts !== 'client' || ![0, 1].includes(direction) || result.language !== expected || !Number.isInteger(result.sequence))
                  throw Error('Некорректный результат перевода для локальной озвучки.');
                native = {synthesisMs: 0, elapsedMs: 0};
                for (const part of speechChunks(result.translation)) {
                  const rendered = await chrome.runtime.sendMessage({type: 'native-synthesize', text: part, language: result.language});
                  if (rendered?.error || !rendered?.audio) throw Error(rendered?.error || 'Локальный Piper не вернул звук.');
                  if (state !== current) return;
                  native.synthesisMs += rendered.synthesisMs || 0;
                  native.elapsedMs += rendered.elapsedMs ?? rendered.synthesisMs ?? 0;
                  await playIncoming(current, Uint8Array.from(atob(rendered.audio), ch => ch.charCodeAt(0)).buffer, direction);
                }
              }
              const response = await chrome.runtime.sendMessage({type: 'translation-status', text: result.translation,
                original: result.text, latencyMs: result.latency_ms + (native?.elapsedMs ?? native?.synthesisMs ?? 0),
                timingsMs: {...result.timings_ms,
                  queue: (result.timings_ms?.queue || 0) + (native ? Math.max(0, (native.elapsedMs ?? native.synthesisMs) - native.synthesisMs) : 0),
                  tts: native?.synthesisMs ?? result.timings_ms?.tts}, direction: result.direction});
              if (response?.error) throw Error(response.error);
            }
          } else {
            if (message.tts === 'client') throw Error('Сервер прислал аудио вместо текста для локальной озвучки.');
            const bytes = new Uint8Array(event.data);
            if (current.audioResults[bytes[0]]?.shift() === false) return;
            if (bytes[0] === 0 || bytes[0] === 1) await playIncoming(current, event.data.slice(1), bytes[0]);
          }
        } catch (error) {
          if (state !== current) return;
          if (current.finishing) { current.finishResolve?.(false); return; }
          clearTimeout(timer); reject(error);
          chrome.runtime.sendMessage({type: 'failed', error: error.message});
        }
      };
      current.ws.onmessage = event => {
        let result;
        try { if (typeof event.data === 'string') result = JSON.parse(event.data); }
        catch { return handle(event); }
        let recorded = Promise.resolve(true);
        if (['recognized', 'translation'].includes(result?.type) && Number.isInteger(result.sequence)) {
          // Journal and display recognition immediately, even while Piper is busy.
          recorded = current.journal = current.journal.then(async () => {
            if (state !== current) return false;
            const saved = await chrome.runtime.sendMessage({type: 'journal', entry: {
              ...result, conversation: message.conversation, received_at: result.received_at || Date.now()
            }});
            if (saved?.error) throw Error(saved.error);
            return true;
          }).catch(error => {
            chrome.runtime.sendMessage({type: 'failed', error: error.message}); return false;
          });
          if (result.type === 'recognized') return recorded;
        }
        const direction = result?.direction ?? (typeof event.data !== 'string' ? new Uint8Array(event.data)[0] : undefined);
        if (direction !== 0 && direction !== 1) return handle(event);
        // Decode, synthesize and schedule each speaker in wire order.
        current.chains[direction] = current.chains[direction].then(async () => { if (await recorded) await handle(event); });
        return current.chains[direction];
      };
    });
    current.capture = await CTpcm(current.context, current.stream, samples => send(1, samples), chrome.runtime.getURL('pcm-worklet.js'));
  } catch (error) { await stop(); throw error; }
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.target !== 'offscreen') return;
  const task = message.type === 'start' ? start(message) : message.type === 'stop' ? stop() : Promise.resolve(send(0, message.samples));
  task.then(result => respond({ok: true, ...result})).catch(error => respond({error: error.message}));
  return true;
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local' || !changes.hearOwnTranslation || !state) return;
  state.hearOwnTranslation = changes.hearOwnTranslation.newValue === true;
  for (const gain of state.monitors) gain.gain.value = state.hearOwnTranslation ? 0.55 : 0;
});