// Continuous linear resampling; wire frames are 20 ms mono PCM16.
globalThis.CTpcm = async function(context, stream, send, moduleURL) {
  await context.audioWorklet.addModule(moduleURL);
  const source = context.createMediaStreamSource(stream);
  const processor = new AudioWorkletNode(context, 'ct-pcm', {channelCount: 1, channelCountMode: 'explicit'});
  const silent = context.createGain(); silent.gain.value = 0;
  const step = context.sampleRate / 16000;
  let received = 0, position = 0, previous = 0, pending = [];
  processor.port.onmessage = event => {
    const input = event.data;
    const end = received + input.length - 1;
    while (position <= end) {
      const relative = position - received;
      const index = Math.floor(relative), fraction = relative - index;
      const a = index < 0 ? previous : input[index];
      const b = input[Math.min(index+1, input.length-1)];
      pending.push(Math.round(Math.max(-1, Math.min(1, a+(b-a)*fraction))*32767));
      position += step;
      if (pending.length === 320) {
        send(pending); pending = [];
      }
    }
    received += input.length; previous = input[input.length-1];
  };
  source.connect(processor).connect(silent).connect(context.destination);
  return () => { processor.port.onmessage = null; processor.port.close(); source.disconnect(); processor.disconnect(); silent.disconnect(); };
};
