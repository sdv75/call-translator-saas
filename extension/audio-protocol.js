'use strict';
(() => {
  function frame(direction, samples) {
    if (!['incoming','outgoing'].includes(direction) || !Array.isArray(samples) || samples.length !== 320 ||
        !samples.every(value => Number.isInteger(value) && value >= -32768 && value <= 32767))
      throw Error('Некорректный аудиокадр.');
    const packet = new ArrayBuffer(641), view = new DataView(packet);
    view.setUint8(0, direction === 'outgoing' ? 0 : 1);
    samples.forEach((value,index) => view.setInt16(1+index*2, value, true));
    return packet;
  }
  function chunks(text, limit = 1400) {
    if (typeof text !== 'string' || !text.trim() || text.length > 16000) throw Error('Некорректный текст озвучки.');
    const result = [];
    while (text.length > limit) {
      let end = text.lastIndexOf(' ',limit);
      if (end < limit/2) end = limit;
      if (/[\uD800-\uDBFF]/.test(text[end-1])) end--;
      result.push(text.slice(0,end)); text = text.slice(end);
    }
    if (text) result.push(text);
    return result;
  }
    function speechChunks(text) {
      // Preserve every character, but start speech after a sentence instead of
      // waiting for an entire multi-sentence translation to be synthesized.
      chunks(text);
      const result=[];let start=0;
      for(const match of text.matchAll(/[.!?…]["»”)]*\s+/gu)){
        const end=match.index+match[0].length,part=text.slice(start,end);
        if(/[\p{L}\p{N}]/u.test(part)){result.push(...chunks(part,240));start=end;}
      }
      if(start<text.length)result.push(...chunks(text.slice(start),240));
      return result;
    }
    function websocketURL(base) {
    const url = new URL(CTProtocol.serviceURL(base));
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    url.pathname = url.pathname.replace(/\/$/,'') + '/ws';
    return url.href;
  }
    const api = {frame, chunks, speechChunks, websocketURL};
  globalThis.CTAudio = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
