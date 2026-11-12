const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

(async () => {
  let listener, socket, settingsListener;
  const gains = [];
  const sent = [];
  let readyMode = 'server', localPlays = 0, graceful = false;
  class Socket {
    static OPEN = 1;
    constructor() { this.readyState = 1; socket = this; setImmediate(() => this.onmessage({data: JSON.stringify({type: 'ready', tts: readyMode, graceful_stop: graceful})})); }
    send(data) {
      if (typeof data === 'string' && JSON.parse(data).type === 'stop') {
        setImmediate(async () => {
          await this.onmessage({data: JSON.stringify({type: 'recognized', direction: 0, sequence: 1, text: 'final tail'})});
          await this.onmessage({data: JSON.stringify({type: 'translation', direction: 0, sequence: 1, text: 'final tail', translation: 'последние слова', tts: 'client', language: 'en'})});
          await this.onmessage({data: JSON.stringify({type: 'finished'})});
        });
      }
    }
    close() {}
  }
  const context = {
    chrome: {storage: {onChanged: {addListener: fn => { settingsListener = fn; }}}, runtime: {
      getURL: name => name,
      sendMessage: async message => {
        sent.push(message);
        if (message.type === 'native-synthesize') {
          if (message.text === 'slow') await new Promise(resolve => setTimeout(resolve, 25));
          return {audio: Buffer.from('RIFF' + message.text).toString('base64'), synthesisMs: 10};
        }
        return {ok: true};
      },
      onMessage: {addListener: fn => { listener = fn; }}
    }},
    fetch: async () => ({json: async () => ({token: 'test-only'})}),
    navigator: {mediaDevices: {getUserMedia: async () => ({getTracks: () => []})}},
    AudioContext: class {
      constructor() { this.currentTime = 0; this.destination = {}; }
      async resume() {} async close() {} async decodeAudioData() { return {duration: 1}; }
      createGain() { const node = {gain: {}, connect() {}, disconnect() {}}; gains.push(node); return node; }
      createBufferSource() { return {connect() {}, start() { localPlays++; }}; }
    },
    WebSocket: Socket, CTpcm: () => () => {}, setTimeout, clearTimeout,
    Uint8Array, ArrayBuffer, DataView, btoa: text => Buffer.from(text, 'binary').toString('base64'),
    atob: text => Buffer.from(text, 'base64').toString('binary')
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'offscreen.js'), 'utf8'), context);
  const result = await new Promise(resolve => listener({target: 'offscreen', type: 'start'}, {}, resolve));
  assert.equal(result.ok, true);
  await socket.onmessage({data: JSON.stringify({type: 'translation', translation: 'Hello'})});
  assert.equal(sent.length, 1);
  assert.equal(sent[0].type, 'translation-status');
  assert.equal(sent[0].text, 'Hello');
  sent.length = 0;
  for (const sequence of [1, 1, 1, 2]) {
    await socket.onmessage({data: JSON.stringify({type: 'translation', direction: 0,
      sequence, text: 'Привет', translation: 'Hello'})});
    await socket.onmessage({data: Uint8Array.from([0, 82, 73, 70, 70]).buffer});
  }
  assert.equal(sent.filter(message => message.type === 'translated-audio').length, 2);
  assert.equal(sent.filter(message => message.type === 'translation-status').length, 2);
  assert.equal(sent.find(message => message.type === 'translation-status').original, 'Привет');
  readyMode = 'client';
  const started = await new Promise(resolve => listener({target: 'offscreen', type: 'start', tts: 'client', source: 'ru', language: 'en'}, {}, resolve));
  assert.equal(started.ok, true);
  sent.length = 0;
  for (const [direction, language] of [[0, 'en'], [1, 'ru']]) {
    const event = {data: JSON.stringify({type: 'translation', direction, sequence: 1, tts: 'client',
      language, text: 'source', translation: 'translated', latency_ms: 20, timings_ms: {queue: 0, translation: 20, tts: 0}})};
    await socket.onmessage(event);
    await socket.onmessage(event); // Duplicate results must never re-synthesize.
  }
  assert.equal(sent.filter(message => message.type === 'native-synthesize').length, 2);
  assert.equal(sent.filter(message => message.type === 'translated-audio').length, 2);
  assert.equal(localPlays, 4);
  assert.equal(gains.at(-2).gain.value, 0);
  assert.equal(gains.at(-1).gain.value, 0.55);
  assert.deepEqual(sent.filter(m => m.type === 'translated-audio').map(m => m.ownTranslation), [false, true]);
  settingsListener({hearOwnTranslation: {newValue: true}}, 'local');
  assert.equal(gains.at(-2).gain.value, 0.55);
  settingsListener({hearOwnTranslation: {newValue: false}}, 'local');
  assert.equal(gains.at(-2).gain.value, 0);
  assert.equal(sent.filter(message => message.type === 'translation-status')[0].timingsMs.tts, 10);
  assert(!sent.some(message => message.type === 'failed'));
  sent.length = 0;
  await Promise.all(['slow', 'fast'].map((translation, index) => socket.onmessage({data: JSON.stringify({
    type: 'translation', direction: 0, sequence: index + 2, tts: 'client', language: 'en', text: translation, translation
  })})));
  assert.deepEqual(sent.filter(message => message.type === 'translated-audio').map(message =>
    Buffer.from(message.audio, 'base64').toString()), ['RIFFslow', 'RIFFfast']);
  assert.equal(sent[0].type, 'journal');
  console.log('Concurrent results preserve speech order and journal before synthesis: PASS');
  await new Promise(resolve => listener({target: 'offscreen', type: 'start', tts: 'client', source: 'uk', language: 'en'}, {}, resolve));
  sent.length = 0;
  for (const [direction, language] of [[0, 'en'], [1, 'uk']]) {
    await socket.onmessage({data: JSON.stringify({type: 'translation', direction, language, sequence: 1,
      tts: 'client', text: 'Привіт', translation: 'Hello'})});
  }
  assert.deepEqual(sent.filter(message => message.type === 'native-synthesize').map(message => message.language), ['en', 'uk']);
  assert(!sent.some(message => message.type === 'failed'));
  sent.length = 0;
  const longText = ('A complete sentence with every word preserved. ').repeat(100);
  await socket.onmessage({data: JSON.stringify({type: 'translation', direction: 0, language: 'en', sequence: 2,
    tts: 'client', text: 'long source', translation: longText})});
  const parts = sent.filter(message => message.type === 'native-synthesize').map(message => message.text);
  assert(parts.length > 1 && parts.every(part => part.length <= 1400));
  assert.equal(parts.join(''), longText);
  assert.equal(sent.filter(message => message.type === 'translated-audio').length, parts.length);
  assert(!sent.some(message => message.type === 'failed'));
  sent.length = 0;
  const busy = socket.onmessage({data: JSON.stringify({type: 'translation', direction: 0, language: 'en', sequence: 3,
    tts: 'client', text: 'previous sentence', translation: 'slow'})});
  await new Promise(setImmediate);
  await socket.onmessage({data: JSON.stringify({type: 'recognized', direction: 0, sequence: 4, text: 'newly spoken words', partial: true})});
  assert(sent.some(message => message.type === 'journal' && message.entry.text === 'newly spoken words'));
  assert(!sent.some(message => message.type === 'translated-audio'));
  await busy;
  console.log('Long translation has no lost chunks; new recognition bypasses busy TTS: PASS');
  graceful = true;
  await new Promise(resolve => listener({target: 'offscreen', type: 'start', tts: 'client', source: 'uk', language: 'en', conversation: 'test-session'}, {}, resolve));
  sent.length = 0;
  const stopped = await new Promise(resolve => listener({target: 'offscreen', type: 'stop'}, {}, resolve));
  assert.equal(stopped.complete, true);
  assert(sent.some(message => message.type === 'journal' && message.entry.translation === 'последние слова' && message.entry.conversation === 'test-session'));
  assert(!sent.some(message => ['native-synthesize', 'failed'].includes(message.type)));
  console.log('Stop waits for final STT/translation journal and retains conversation identity: PASS');
  console.log('Native synthesis in both directions, playback routing and duplicate rejection: PASS');
  console.log('Offscreen translation with runtime API only: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
