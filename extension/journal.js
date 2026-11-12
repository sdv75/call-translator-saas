'use strict';
// Private to the SaaS extension. No legacy IndexedDB databases are opened.
globalThis.CTJournal = (() => {
  let opening;
  function database() {
    return opening ||= new Promise((resolve,reject) => {
      const request = indexedDB.open('ct-saas-transcripts',1);
      request.onupgradeneeded = () => {
        request.result.createObjectStore('sessions',{keyPath:'id'});
        const events=request.result.createObjectStore('events',{keyPath:'id'});
        events.createIndex('session','session');
      };
      request.onsuccess = () => { request.result.onversionchange=()=>request.result.close(); resolve(request.result); };
      request.onerror = () => reject(Error('Не удалось открыть локальные стенограммы.'));
    });
  }
  async function putSession(session) {
    const db=await database();
    return new Promise((resolve,reject)=>{
      const tx=db.transaction('sessions','readwrite'); tx.objectStore('sessions').put(session);
      tx.oncomplete=resolve; tx.onerror=tx.onabort=()=>reject(Error('Не удалось сохранить сеанс локально.'));
    });
  }
  async function record(session,event) {
    if (!['incoming','outgoing'].includes(event.direction) || !Number.isSafeInteger(event.sequence) || event.sequence<1)
      throw Error('Некорректное событие стенограммы.');
    const db=await database();
    return new Promise((resolve,reject)=>{
      const tx=db.transaction('events','readwrite'), store=tx.objectStore('events');
      const id=`${session}:${event.direction}:${event.sequence}`, request=store.get(id);
      request.onsuccess=()=>{
        const previous=request.result || {id,session,direction:event.direction,sequence:event.sequence,received_at:Date.now()};
        store.put({...previous,original:typeof event.original==='string'?event.original:previous.original || '',
          text:event.type==='translation' ? event.text : previous.text || '',
          timing:{...previous.timing,...event.timing},
          uncertain:typeof event.uncertain==='boolean'?event.uncertain:previous.uncertain===true});
      };
      tx.oncomplete=resolve; tx.onerror=tx.onabort=()=>reject(Error('Не удалось сохранить фрагмент локально.'));
    });
  }
  async function sessions() {
    const db=await database();
    return new Promise((resolve,reject)=>{
      const request=db.transaction('sessions').objectStore('sessions').getAll();
      request.onsuccess=()=>resolve(request.result.sort((a,b)=>b.started_at-a.started_at));
      request.onerror=()=>reject(Error('Не удалось прочитать локальные сеансы.'));
    });
  }
  async function entries(session) {
    const db=await database();
    return new Promise((resolve,reject)=>{
      const request=db.transaction('events').objectStore('events').index('session').getAll(session);
      request.onsuccess=()=>resolve(request.result.sort((a,b)=>a.received_at-b.received_at || a.sequence-b.sequence));
      request.onerror=()=>reject(Error('Не удалось прочитать локальную стенограмму.'));
    });
  }
  return {putSession,record,sessions,entries};
})();
