(() => {
  let current = null;
  async function stop() {
    const state = current; current = null;
    if (!state) return;
    clearInterval(state.watch);
    state.capture();
    for (const source of state.sources) { try { source.stop(); } catch (_) {} }
    await Promise.allSettled(state.senders.map(({sender, track}) => {
      // Meet owns mute and may already have installed another microphone track.
      if (sender.track !== state.output) return;
      track.enabled = track.enabled && state.output.enabled;
      return sender.replaceTrack(track);
    }));
    state.destination.stream.getTracks().forEach(track => track.stop());
    await state.context.close();
  }
  async function start(options = {}) {
    await stop();
    await window.__callTranslatorProbe.restore();
    const senders = window.__callTranslatorProbe.audioSenders();
    if (!senders.length) throw Error('Войдите в Meet и включите микрофон перед запуском перевода.');
    const context = new AudioContext({sampleRate: 48000});
    await Promise.race([context.resume(), new Promise((_, reject) => setTimeout(() => reject(Error('Нажмите на страницу Meet и повторите запуск.')), 3000))]).catch(async e => { await context.close(); throw e; });
    const destination = context.createMediaStreamDestination();
    destination.channelCount = senders[0].track.getSettings().channelCount || 1;
    destination.channelCountMode = 'explicit';
    const state = {hearOwnTranslation: options.hearOwnTranslation === true, monitors: new Set(), context, destination, senders, sources: new Set(), next: 0, captureBlockedUntil: 0, capture: () => {}};
    current = state;
    try {
      const output = destination.stream.getAudioTracks()[0];
      state.output = output;
      state.canSend = () => output.enabled && output.readyState === 'live' &&
        senders.every(item => item.track.enabled && item.track.readyState === 'live');
      for (const item of senders) await item.sender.replaceTrack(output);
      state.capture = await CTpcm(context, new MediaStream([senders[0].track]), samples => {
        if (current === state)
          // Duplex keeps capture active. The optional speaker guard preserves
          // the PCM clock with silence while output and its echo tail play.
          window.postMessage({ct: 'microphone', samples: state.canSend() && (!options.echoGuard || context.currentTime >= state.captureBlockedUntil)
            ? samples : Array(320).fill(0)}, location.origin);
      }, options.workletURL);
      state.watch = setInterval(() => {
        const probe = window.__callTranslatorProbe;
        if (probe.hasAudioConnection && !probe.hasAudioConnection(senders.map(item => item.sender))) {
          clearInterval(state.watch);
          window.postMessage({ct: 'translation-ended'}, location.origin);
          stop().catch(() => {}); return;
        }
        // Never re-enable a track muted by Meet.
        if (!senders.every(item => item.track.enabled && item.track.readyState === 'live')) output.enabled = false;
        if (!state.canSend()) {
          for (const source of state.sources) { try { source.stop(); } catch (_) {} }
          state.sources.clear(); state.next = 0;
          state.captureBlockedUntil = context.currentTime + .8;
        }
        if (senders.some(item => item.sender.track !== output || item.track.readyState !== 'live')) {
          clearInterval(state.watch);
          window.postMessage({ct: 'translation-failed', error: 'Meet сменил аудиодорожку. Перевод остановлен, включён обычный микрофон. Включите перевод повторно.'}, location.origin);
          stop().catch(() => {});
        }
      }, 50);
    } catch (error) { await stop(); throw error; }
  }
  async function audio(payload) {
    const base64 = typeof payload === 'string' ? payload : payload.audio;
    const state = current;
    if (!state || !state.canSend()) return;
    const bytes = Uint8Array.from(atob(base64), ch => ch.charCodeAt(0));
    const buffer = await state.context.decodeAudioData(bytes.buffer);
    if (current !== state || !state.canSend()) return;
    const source = state.context.createBufferSource(); source.buffer = buffer;
    const gain = state.context.createGain();
    const own = payload.ownTranslation === true;
    gain.gain.value = own ? (state.hearOwnTranslation ? 0.55 : 0) : 1;
    if (own) state.monitors.add(gain);
    source.connect(gain); gain.connect(state.destination); state.sources.add(source);
    source.onended = () => { state.sources.delete(source); source.disconnect(); gain.disconnect(); state.monitors.delete(gain); };
    const when = Math.max(state.context.currentTime, state.next);
    state.next = when + buffer.duration;
    state.captureBlockedUntil = Math.max(state.captureBlockedUntil, state.next + .8);
    source.start(when);
  }
  window.__CTtranslate = Object.freeze({start, stop, audio, monitor(enabled) {
    if (!current) return;
    current.hearOwnTranslation = enabled === true;
    for (const gain of current.monitors) gain.gain.value = enabled === true ? 0.55 : 0;
  }});
  window.addEventListener('message', event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.ct !== 'runtime-lost') return;
    stop().catch(() => {});
    let notice = document.getElementById('ct-runtime-notice');
    if (!notice) {
      notice = document.createElement('div'); notice.id = 'ct-runtime-notice';
      notice.style.cssText = 'position:fixed;top:12px;right:12px;z-index:2147483647;background:#fff;color:#111;padding:16px;border:2px solid #b44;max-width:360px;font:14px sans-serif';
      document.documentElement.append(notice);
    }
    notice.textContent = 'Связь с расширением потеряна. Обновите вкладку Meet и включите перевод заново.';
  });
  window.addEventListener('pagehide', () => { stop(); });
})();
