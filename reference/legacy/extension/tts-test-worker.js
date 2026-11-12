import * as engine from './vendor/browser-tts/engine.js';
import {VOICES} from './tts-test-common.mjs';

let queue = Promise.resolve();
self.onmessage = ({data}) => {
  queue = queue.then(async () => {
    const {id, action, language, text} = data;
    try {
      let result;
      if (action === 'stored') {
        result = {};
        for (const [lang, voice] of Object.entries(VOICES)) result[lang] = await engine.stored(voice.id);
      } else {
        const voice = VOICES[language];
        if (!voice) throw Error('Неизвестный язык.');
        if (action === 'download') result = await engine.download(voice.id, progress => self.postMessage({id, progress}));
        else if (action === 'remove') { await engine.remove(voice.id); result = {}; }
        else if (action === 'synthesize') result = await engine.synthesize(voice.id, text);
        else throw Error('Неизвестная операция.');
      }
      self.postMessage({id, result}, result?.wav ? [result.wav] : []);
    } catch (error) {
      // Never include user text in console or errors forwarded to the report.
      self.postMessage({id, error: String(error.message || error)});
    }
  });
};
