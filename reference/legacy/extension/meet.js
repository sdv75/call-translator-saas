/* Feasibility gate: replace actual outgoing senders, never touch camera tracks. */
(() => {
  if (window.__callTranslatorProbe) return;
  const NativePeer = window.RTCPeerConnection;
  const peers = new Set();
  let session = null;
  let report = null;
  let speech = null;
  const log = text => { if (report) report.textContent += text + '\n'; };
  async function counters(senders) {
    let packets = 0;
    let bytes = 0;
    for (const {sender} of senders) {
      const stats = await sender.getStats();
      stats.forEach(stat => {
        if (stat.type === 'outbound-rtp' && (stat.kind === 'audio' || stat.mediaType === 'audio')) {
          packets += stat.packetsSent || 0;
          bytes += stat.bytesSent || 0;
        }
      });
    }
    return {packets, bytes};
  }
  window.RTCPeerConnection = new Proxy(NativePeer, {
    construct(Target, args, NewTarget) {
      const peer = Reflect.construct(Target, args, NewTarget);
      peers.add(peer);
      peer.addEventListener('connectionstatechange', () => {
        if (peer.connectionState === 'closed') peers.delete(peer);
      });
      return peer;
    }
  });
  async function restore() {
    const current = session;
    if (!current) return 'Обычный микрофон уже включён.';
    session = null;
    clearTimeout(current.timer);
    clearInterval(current.muteWatch);
    const output = current.destination.stream.getAudioTracks()[0];
    const results = await Promise.allSettled(current.senders.map(({sender, track}) => {
      if (sender.track !== output) return;
      track.enabled = track.enabled && output.enabled;
      return sender.replaceTrack(track);
    }));
    try { current.oscillator.stop(); } catch (_) { /* not started */ }
    current.destination.stream.getTracks().forEach(track => track.stop());
    await current.context.close();
    if (results.some(result => result.status === 'rejected')) return 'Не удалось восстановить дорожку. Обновите вкладку Meet.';
    return 'Микрофон восстановлен.';
  }
  async function probe() {
    await restore();
    log('Соединений WebRTC: ' + peers.size);
    for (const peer of peers) {
      log('Соединение: ' + peer.connectionState + '; аудиодорожек: ' + peer.getSenders().filter(s => s.track?.kind === 'audio').length);
    }
    const senders = [...peers].flatMap(peer => peer.getSenders())
      .filter(sender => sender.track?.kind === 'audio' && sender.track.readyState === 'live' && sender.track.enabled)
      .map(sender => ({sender, track: sender.track}));
    if (!senders.length) return 'Нет исходящей аудиодорожки. Войдите в звонок и включите микрофон.';
    const context = new AudioContext({sampleRate: 48000});
    await Promise.race([context.resume(), new Promise((_, reject) => setTimeout(() => reject(Error('Браузер не разрешил запуск AudioContext. Нажмите кнопку непосредственно на странице Meet.')), 3000))]).catch(async error => { await context.close(); throw error; });
    log('AudioContext: ' + context.state);
    const destination = context.createMediaStreamDestination();
    destination.channelCount = senders[0].track.getSettings().channelCount || 1;
    destination.channelCountMode = 'explicit';
    if (!speech) { await context.close(); throw Error('Откройте проверку через окно расширения.'); }
    const gain = context.createGain(); gain.gain.value = 1;
    const oscillator = context.createBufferSource();
    try {
      oscillator.buffer = await context.decodeAudioData(Uint8Array.from(atob(speech), ch => ch.charCodeAt(0)).buffer);
    } catch (error) { await context.close(); throw error; }
    const duration = oscillator.buffer.duration;
    let peak = 0;
    for (const value of oscillator.buffer.getChannelData(0)) peak = Math.max(peak, Math.abs(value));
    log('Запись речи: ' + duration.toFixed(1) + ' с; пиковый уровень: ' + peak.toFixed(3));
    oscillator.connect(gain).connect(destination);
    const track = destination.stream.getAudioTracks()[0];
    log('Активных отправителей: ' + senders.length + '; каналов сигнала: ' + track.getSettings().channelCount);
    const before = await counters(senders);
    session = {context, destination, oscillator, senders};
    try {
      for (const item of senders) await item.sender.replaceTrack(track);
      log('replaceTrack: успешно');
      oscillator.start();
      session.muteWatch = setInterval(() => {
        if (!senders.every(item => item.track.enabled && item.track.readyState === 'live')) track.enabled = false;
        if (senders.some(item => item.sender.track !== track)) {
          log('Meet заменил тестовую дорожку своей дорожкой.');
          restore().then(log).catch(error => log(error.message));
        }
      }, 25);
      session.timer = setTimeout(async () => {
        try {
          const after = await counters(senders);
          log('За тест: RTP пакетов ' + (after.packets-before.packets) + ', байт ' + (after.bytes-before.bytes));
          log('Состояние сигнала: ' + track.readyState + ', enabled=' + track.enabled + ', context=' + context.state);
        } catch (error) { log('Ошибка статистики: ' + error.message); }
        finally { log(await restore()); }
      }, Math.ceil((duration + .5) * 1000));
      return 'Вместо микрофона передана фраза: This is a translation audio test. One two three. Это ещё не подтверждение доставки.';
    } catch (error) { await restore(); throw error; }
  }
  function mount(sample) {
    speech = sample;
    const existing = document.getElementById('call-translator-diagnostic');
    if (existing) return 'Панель проверки уже открыта на странице Meet.';
    const panel = document.createElement('div');
    panel.id = 'call-translator-diagnostic';
    panel.style.cssText = 'position:fixed;top:15px;right:15px;z-index:2147483647;background:white;color:black;padding:16px;width:370px;border:2px solid #456;font:14px sans-serif;box-shadow:0 4px 20px #0008;';
    const button = document.createElement('button');
    button.textContent = 'Передать тестовую речь собеседнику';
    report = document.createElement('pre');
    report.style.cssText = 'white-space:pre-wrap;max-height:280px;overflow:auto;font-size:12px';
    button.onclick = async () => {
      button.disabled = true;
      report.textContent = '';
      try { log(await probe()); } catch (error) { log(error.name + ': ' + error.message); }
      finally { button.disabled = false; }
    };
    const close = document.createElement('button'); close.textContent = 'Закрыть';
    close.onclick = async () => { await restore(); panel.remove(); report = null; };
    panel.append(button, report, close);
    document.documentElement.append(panel);
    return 'Нажмите кнопку проверки непосредственно на странице Meet. После теста пришлите текст панели.';
  }
  function audioSenders() {
    return [...peers].flatMap(peer => peer.getSenders())
      .filter(sender => sender.track?.kind === 'audio' && sender.track.readyState === 'live' && sender.track.enabled)
      .map(sender => ({sender, track: sender.track}));
  }
  function hasAudioConnection(senders) {
    return [...peers].some(peer => peer.connectionState !== 'closed' && peer.signalingState !== 'closed' &&
      peer.getSenders().some(sender => senders.includes(sender)));
  }
  window.__callTranslatorProbe = Object.freeze({probe, restore, mount, audioSenders, hasAudioConnection});
  window.addEventListener('pagehide', () => { restore(); });
})();
