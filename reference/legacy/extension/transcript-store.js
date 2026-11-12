globalThis.CTjournal = (() => {
  function open(name, store) {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(name, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(store, {keyPath: 'id'});
      request.onsuccess = () => { request.result.onversionchange = () => request.result.close(); resolve(request.result); };
      request.onerror = () => reject(request.error);
    });
  }
  const sessions = open('ct-conversation-sessions', 'sessions');
  const database = new Promise((resolve, reject) => {
    const request = indexedDB.open('ct-conversations', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('events', {keyPath: 'id'});
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return {
    async saveSession(session) {
      const db = await sessions;
      return new Promise((resolve, reject) => {
        const tx = db.transaction('sessions', 'readwrite'); tx.objectStore('sessions').put(session);
        tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
      });
    },
    async session(id) {
      return (await this.conversations()).find(session => session.id === id);
    },
    async conversations() {
      const db = await sessions;
      const saved = await new Promise((resolve, reject) => {
        const request = db.transaction('sessions').objectStore('sessions').getAll();
        request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
      });
      const byId = new Map(saved.map(session => [session.id, session]));
      // Existing journals remain readable as separate conversations.
      for (const event of await this.all()) {
        if (!event.conversation) continue;
        const previous = byId.get(event.conversation);
        if (!previous) byId.set(event.conversation, {id: event.conversation, started_at: event.received_at, state: 'legacy'});
        else if (previous.state === 'legacy') previous.started_at = Math.min(previous.started_at, event.received_at);
      }
      return [...byId.values()].sort((a,b) => b.started_at - a.started_at);
    },
    async entries(id) { return (await this.all()).filter(event => event.conversation === id); },
    async put(event) {
      const db = await database;
      return new Promise((resolve, reject) => {
        const tx = db.transaction('events', 'readwrite');
        tx.objectStore('events').put(event);
        tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error || Error('Не удалось сохранить стенограмму'));
      });
    },
    async all() {
      const db = await database;
      return new Promise((resolve, reject) => {
        const request = db.transaction('events').objectStore('events').getAll();
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
    }
  };
})();
