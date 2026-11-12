'use strict';
class LocalVoiceClient {
  constructor(runtime) { this.runtime = runtime; this.port = null; this.pending = new Map(); this.nextId = 0; }
  close(reason = 'Локальный компонент отключён.') {
    const port = this.port; this.port = null;
    for (const item of this.pending.values()) { clearTimeout(item.timer); item.reject(Error(reason)); }
    this.pending.clear();
    port?.disconnect();
  }
  connect() {
    if (this.port) return;
    const port = this.runtime.connectNative('org.call_translator.saas.local'); this.port = port;
    port.onDisconnect.addListener(() => {
      void this.runtime.lastError;
      if (this.port === port) {this.close('Не удалось подключить локальный компонент.');this.onLost?.();}
    });
    port.onMessage.addListener(message => {
      if (this.port !== port || !message || typeof message !== 'object') return;
      const item = this.pending.get(message.id);
      if (!item) return;
      try {
        if (message.error) throw Error(item.type.startsWith('transcript-')&&message.error==='unsupported_request'?'Для папки стенограмм обновите программу установщиком из кабинета.':message.error === 'component_update_required' ? 'Для этого голоса обновите локальный компонент.' :
          ['call_active','local_busy'].includes(message.error) ? 'Локальный компонент занят. Завершите звонок или дождитесь установки.' : 'Локальная операция не выполнена. Проверьте каталог и компонент.');
        if (message.type === 'audio-chunk') {
          if (!item.audio || message.index !== item.chunks.length || typeof message.data !== 'string' ||
              message.data.length > 262144 || item.chunks.length >= 86 || !/^[A-Za-z0-9+/]*={0,2}$/.test(message.data))
            throw Error('Некорректный аудиоответ локального компонента.');
          item.chunks.push(message.data); return;
        }
        let result;
        if (item.type === 'status') result = CTProtocol.localStatus(message, message.id);
        else if (item.audio && message.type === 'audio-end' && Number.isInteger(message.bytes) &&
                 message.bytes > 44 && message.bytes <= 16*1024*1024 && message.chunks === item.chunks.length) {
          const audio = item.chunks.join(''), binary = atob(audio);
          if (binary.length !== message.bytes || !binary.startsWith('RIFF') || binary.slice(8,12) !== 'WAVE')
            throw Error('Повреждён звук локального компонента.');
          result = {audio};
          if(Number.isFinite(message.synthesis_ms)&&message.synthesis_ms>=0&&message.synthesis_ms<=180000)result.synthesis_ms=message.synthesis_ms;
        } else {
          const expected = {'transcript-folder-status':'transcript-folder-status','transcript-folder-choose':'transcript-folder-choose',
                            'transcript-folder-default':'transcript-folder-default','transcript-folder-open':'transcript-folder-open','transcript-write':'transcript-write',
                            'catalog-info': 'catalog-info', 'install-voice': 'voice-installed', 'remove-voice':'voice-removed', 'select-voice': 'voice-selected',
                            'begin-call': 'call-ready', 'end-call': 'call-ended'}[item.type];
          if (!expected || message.type !== expected) throw Error('Несовместимый локальный компонент.');
          result = message;
        }
        clearTimeout(item.timer); this.pending.delete(message.id); item.resolve(result);
      } catch (error) {
        clearTimeout(item.timer); this.pending.delete(message.id); item.reject(error);
      }
    });
  }
  request(type, payload = {}) {
    this.connect();
    if (this.pending.size >= 4) return Promise.reject(Error('Очередь локального компонента занята.'));
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timeout = ['install-voice','transcript-folder-choose'].includes(type) ? 310000 : ['begin-call','preview-voice'].includes(type) ? 180000 : 90000;
      const timer = setTimeout(() => this.close('Локальный компонент не ответил вовремя.'), timeout);
      this.pending.set(id, {type, resolve, reject, timer, chunks: [], audio: ['synthesize','preview-voice'].includes(type)});
      try { this.port.postMessage({id, type, ...payload}); }
      catch { this.close('Локальный компонент недоступен.'); }
    });
  }
}
globalThis.LocalVoiceClient = LocalVoiceClient;
if (typeof module !== 'undefined') module.exports = LocalVoiceClient;
