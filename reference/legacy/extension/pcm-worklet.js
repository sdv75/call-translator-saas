// Copy input to the resampler in pcm.js; output remains silent.
class CTPCM extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]?.[0];
    if (input) {
      const copy = input.slice();
      this.port.postMessage(copy, [copy.buffer]);
    }
    return true;
  }
}
registerProcessor('ct-pcm', CTPCM);
