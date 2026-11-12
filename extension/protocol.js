'use strict';
(() => {
  function serviceURL(value) {
    const url = new URL(value);
    if (url.username || url.password || url.search || url.hash ||
        !(url.protocol === 'https:' || (url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname))))
      throw Error('Укажите HTTPS-адрес сервиса или localhost для разработки.');
    return url.href.replace(/\/+$/, '');
  }
  function localStatus(data, expectedId = 1) {
    if (!data || data.id !== expectedId || data.protocol !== 1 || !Array.isArray(data.voices) || typeof data.ready !== 'boolean')
      throw Error('Несовместимый ответ локального компонента.');
    return {ready: data.ready, voices: data.voices, version: String(data.version || ''),
          capabilities:Array.isArray(data.capabilities)?data.capabilities.filter(item=>['remove-voice','language-variants','transcript-folders'].includes(item)):[],
            reason: data.reason === 'local_dependencies_missing' ? data.reason : null,
            selected:Object.fromEntries(['incoming','outgoing'].filter(direction=>typeof data.selected?.[direction]==='string').map(direction=>[direction,data.selected[direction]]))};
  }
  function permissionOrigin(service) {
    const url = new URL(serviceURL(service));
    return `${url.protocol}//${url.hostname}/*`;
  }
  const api = {serviceURL, localStatus, permissionOrigin};
  globalThis.CTProtocol = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
