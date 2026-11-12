const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
let Worklet;
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, 'pcm-worklet.js'), 'utf8'), {
  AudioWorkletProcessor: class { constructor() { this.port = {postMessage: frame => {
    assert.equal(frame.length, 128); assert.equal(frame[0], .5);
  }}; } },
  registerProcessor: (name, processor) => { assert.equal(name, 'ct-pcm'); Worklet = processor; }
});
const worklet = new Worklet();
assert.equal(worklet.process([[new Float32Array(128).fill(.5)]]), true);
assert.equal(worklet.process([]), true);
require('./pcm.js');
(async () => { for (const rate of [44100, 48000]) {
  let processor;
  const node = () => ({connect(other) { return other; }, disconnect() {}});
  const context = {sampleRate: rate, destination: {}, createMediaStreamSource: node,
    audioWorklet: {async addModule() {}},
    createGain() { return {...node(), gain: {value: 1}}; }};
  globalThis.AudioWorkletNode = class { constructor() { processor = this; this.port = {close() {}}; } connect(other) { return other; } disconnect() {} };
  const frames = [];
  const close = await CTpcm(context, {}, samples => frames.push(samples), 'pcm-worklet.js');
  for (let offset = 0; offset < rate; offset += 137) {
    const count = Math.min(137, rate-offset);
    processor.port.onmessage({data: new Float32Array(count).fill(.5)});
  }
  assert.equal(frames.length, 50);
  assert(frames.every(frame => frame.length === 320 && frame.every(value => value === 16384)));
  close(); assert.equal(processor.port.onmessage, null);
}
console.log('PCM framing, resampling and cleanup: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
