// Loaded in the service worker; content scripts never get native-host access.
class NativePiperClient {
  constructor(runtime) { this.runtime = runtime; this.pending = new Map(); this.nextId = 0; this.port = null; this.ready = null; }
  close(reason = 'Локальный Piper отключён.') {
    const port = this.port; this.port = null; this.ready = null;
    for (const item of this.pending.values()) { clearTimeout(item.timer); item.reject(Error(reason)); }
    this.pending.clear(); port?.disconnect();
  }
  connect() {
    if (this.port) return;
    const port = this.runtime.connectNative('org.call_translator.piper');
    this.port = port;
    port.onMessage.addListener(message => {
      if (this.port !== port) return;
      const item = this.pending.get(message.id);
      if (!item) return;
      if (message.type === 'audio-chunk') {
        if (message.index !== item.chunks.length || typeof message.data !== 'string' ||
            message.data.length > 300000 || item.chunks.length >= 172) {
          this.close('Некорректный ответ локального Piper.'); return;
        }
        item.chunks.push(message.data); return;
      }
      clearTimeout(item.timer); this.pending.delete(message.id);
      if (message.type === 'error') { item.reject(Error('Локальный Piper не смог создать речь. Перезапустите перевод.')); return; }
      if (message.type === 'ready' && item.type === 'init' && message.version === 1 &&
          ['ru', 'en'].every(language => message.voices?.includes(language))) { item.resolve(message); return; }
      if (message.type === 'audio-end' && item.type === 'synthesize' && message.chunks === item.chunks.length &&
          Number.isInteger(message.bytes) && message.bytes > 44 && message.bytes <= 32 * 1024 * 1024) {
        const audio = item.chunks.join('');
        try {
          const binary = atob(audio);
          if (binary.length !== message.bytes || !binary.startsWith('RIFF')) throw Error();
          item.resolve({audio, synthesisMs: message.synthesisMs});
        } catch { item.reject(Error('Повреждён звук от локального Piper.')); }
        return;
      }
      item.reject(Error('Несовместимая версия локального Piper.'));
    });
    port.onDisconnect.addListener(() => {
      const error = this.runtime.lastError; // Consume Chrome's disconnect error.
      if (this.port !== port) return;
      this.close('Не удалось подключить локальный Piper. Установите компонент и перезапустите перевод.');
      if (this.onLost) this.onLost(error?.message);
    });
  }
  request(type, payload = {}) {
    this.connect();
    if (this.pending.size >= 4) return Promise.reject(Error('Очередь локальной озвучки переполнена. Говорите короче или выберите серверную озвучку.'));
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => this.close('Локальный Piper не ответил вовремя. Перезапустите перевод.'), type === 'init' ? 90000 : 45000);
      this.pending.set(id, {type, resolve, reject, timer, chunks: []});
      try { this.port.postMessage({id, type, ...payload}); }
      catch { this.close('Локальный Piper недоступен.'); }
    });
  }
  init() { return this.ready ||= this.request('init'); }
  async synthesize(text, language) {
    const ready = await this.init();
    if (!['ru', 'en', 'uk'].includes(language) || typeof text !== 'string' || !text.trim() || text.length > 2000)
      throw Error('Некорректный текст или язык для озвучки.');
    if (!ready.voices.includes(language)) throw Error('Обновите локальный компонент Piper: выбранный голос не установлен.');
    return this.request('synthesize', {text, language});
  }
}
globalThis.NativePiperClient = NativePiperClient;
