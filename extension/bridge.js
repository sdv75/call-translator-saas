// ISOLATED world only. An old tab may outlive its extension runtime.
(() => {
  let alive = true;
  let lastSession;
  function invalidate() {
    if (!alive) return;
    alive = false;
    window.removeEventListener('message', microphone);
    window.removeEventListener('pagehide', leaving);
    window.postMessage({ct: 'runtime-lost'}, location.origin);
  }
  function transmit(message) {
    if (!alive) return;
    try {
      const runtime = globalThis.chrome?.runtime;
      if (!runtime?.id || typeof runtime.sendMessage !== 'function') { invalidate(); return; }
      Promise.resolve(runtime.sendMessage(message)).then(result => {
        if (result?.error) invalidate();
      }).catch(invalidate);
    } catch (_) { invalidate(); }
  }
  function microphone(event) {
    if (event.source !== window || event.origin !== location.origin) return;
    const message = event.data;
    if(message?.ct==='microphone-state'&&typeof message.guarded==='boolean'&&Number.isSafeInteger(message.suppressed_ms)&&message.suppressed_ms>=0){
      transmit({type:'microphone-state',sessionId:message.sessionId,guarded:message.guarded,suppressed_ms:message.suppressed_ms});return;
    }
    if (message?.ct === 'translation-ended') { transmit({type: 'tab-ended', sessionId:message.sessionId}); return; }
    if (message?.ct === 'translation-failed') {
      transmit({type: 'page-failed',sessionId:message.sessionId});
      return;
    }
    if (message?.ct !== 'microphone' || !Array.isArray(message.samples) || message.samples.length !== 320) return;
    if (!message.samples.every(n => Number.isInteger(n) && n >= -32768 && n <= 32767)) return;
    lastSession=message.sessionId;
    transmit({type: 'pcm',sessionId:message.sessionId,samples: message.samples});
  }
  function leaving() { transmit({type: 'tab-ended',sessionId:lastSession}); }
  window.addEventListener('message', microphone);
  window.addEventListener('pagehide', leaving);
  try {
    const runtime = globalThis.chrome?.runtime;
    if (!runtime?.id || !runtime.onMessage) { invalidate(); return; }
    runtime.onMessage.addListener((message, sender, respond) => {
      if (message.type === 'bridge-ready') respond({ok: alive});
    });
  } catch (_) { invalidate(); }
})();
