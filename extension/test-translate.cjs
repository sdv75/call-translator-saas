const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

async function fixture(echoGuard = true) {
  const original = {enabled: true, readyState: 'live', getSettings: () => ({channelCount: 1})};
  const output = {enabled: true, readyState: 'live', stop() {}};
  const sender = {track: original, async replaceTrack(track) { this.track = track; }};
  let watch, capture, context, connected = true;
  const messages = [], sources = [], gains = [];
  const window = {
    __callTranslatorProbe: {restore: async () => {}, audioSenders: () => [{sender, track: original}], hasAudioConnection: () => connected},
    addEventListener() {}, postMessage: message => messages.push(message)
  };
  class AudioContext {
    constructor() { this.currentTime = 0; context = this; }
    async resume() {}
    async close() {}
    createMediaStreamDestination() { return {stream: {getAudioTracks: () => [output], getTracks: () => [output]}}; }
    async decodeAudioData() { return {duration: 1}; }
    createGain() { const gain = {gain: {}, connect() {}, disconnect() {}}; gains.push(gain); return gain; }
    createBufferSource() {
      const source = {connect() {}, disconnect() {}, start(when) { this.when = when; }, stop() { this.stopped = true; }};
      sources.push(source); return source;
    }
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'translate.js'), 'utf8'), {
    window, AudioContext, MediaStream: class {},
    CTpcm: (context, stream, fn) => { capture = fn; return () => {}; },
    setInterval: fn => { watch = fn; return 1; }, clearInterval() {},
    setTimeout: () => 1, location: {origin: 'https://meet.google.com'},
    atob: () => '', Uint8Array
  });
  await window.__CTtranslate.start({echoGuard});
  return {window, original, output, sender, messages, sources, gains, context, watch: () => watch(), endCall: () => { connected = false; watch(); }, capture: () => capture(Array(320).fill(100))};
}
(async () => {
  const monitor = await fixture(false);
  await monitor.window.__CTtranslate.audio({audio: '', ownTranslation: true});
  assert.equal(monitor.gains[0].gain.value, 0);
  monitor.window.__CTtranslate.monitor(true);
  assert.equal(monitor.gains[0].gain.value, 0.55);
  await monitor.window.__CTtranslate.audio({audio: '', ownTranslation: false});
  assert.equal(monitor.gains[1].gain.value, 1);
  monitor.window.__CTtranslate.monitor(false);
  assert.equal(monitor.gains[0].gain.value, 0);
  assert.equal(monitor.gains[1].gain.value, 1);
  await monitor.window.__CTtranslate.stop();
  console.log('Own translation toggle affects remote monitor only: PASS');
  const muted = await fixture();
  muted.output.enabled = false; // Meet mutes the replacement track.
  muted.watch();
  assert.equal(muted.output.enabled, false);
  assert(!muted.messages.some(message => message.ct === 'translation-ended'));
  muted.capture();
  assert(muted.messages.at(-1).samples.every(sample => sample === 0));
  await muted.window.__CTtranslate.audio('');
  assert.equal(muted.sources.length, 0);
  await muted.window.__CTtranslate.stop();
  assert.equal(muted.sender.track, muted.original);
  assert.equal(muted.original.enabled, false);

  const replaced = await fixture();
  const newTrack = {enabled: false};
  replaced.sender.track = newTrack;
  await replaced.window.__CTtranslate.stop();
  assert.equal(replaced.sender.track, newTrack);
  assert.equal(newTrack.enabled, false);
  const echo = await fixture();
  echo.capture();
  assert(echo.messages.at(-1).samples.every(sample => sample === 100));
  await echo.window.__CTtranslate.audio('');
  echo.capture();
  assert(echo.messages.at(-1).samples.every(sample => sample === 100),'Remote-only audio must not gate the local microphone');
  echo.window.__CTtranslate.guard({delayMs:0,durationMs:1000});
  echo.capture(); // Simulate the phone speaker coming back into the headset mic.
  assert(echo.messages.at(-1).samples.every(sample => sample === 0));
  echo.context.currentTime = 1.1; // Speech ended but the acoustic tail remains.
  echo.capture();
  assert(echo.messages.at(-1).samples.every(sample => sample === 0));
  assert.equal(echo.output.enabled, true);
  assert.equal(echo.original.enabled, true); // Guard never changes Meet mute state.
  echo.context.currentTime = 1.81;
  echo.capture();
  assert(echo.messages.at(-1).samples.every(sample => sample === 100));
  await echo.window.__CTtranslate.stop();

  const queued = await fixture();
  await queued.window.__CTtranslate.audio('');
  await queued.window.__CTtranslate.audio('');
  queued.window.__CTtranslate.guard({delayMs:1000,durationMs:1000});
  assert.equal(queued.sources[1].when, 1);
  queued.context.currentTime = 2.5;
  queued.capture();
  assert(queued.messages.at(-1).samples.every(sample => sample === 0));
  queued.context.currentTime = 2.81;
  queued.capture();
  assert(queued.messages.at(-1).samples.every(sample => sample === 100));
  await queued.window.__CTtranslate.stop();
  console.log('Phone speaker feedback, echo tail, queued audio and capture recovery: PASS');
  console.log('Meet mute, silent capture, muted playback and track ownership: PASS');
  const duplex = await fixture(false);
  await Promise.all(Array.from({length: 15}, () => duplex.window.__CTtranslate.audio('')));
  assert.equal(duplex.sources.length, 15);
  assert.equal(duplex.sources[14].when, 14);
  duplex.capture();
  assert(duplex.messages.at(-1).samples.every(sample => sample === 100));
  await duplex.window.__CTtranslate.stop();
  console.log('Duplex capture during playback and queues longer than eight seconds: PASS');
  const ended = await fixture(false);
  ended.endCall();
  assert(ended.messages.some(message => message.ct === 'translation-ended'));
  console.log('Meet hangup signals automatic session completion; mute does not: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
