const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, 'bridge.js'), 'utf8');
function setup(sendMessage) {
  const listeners = new Map(), notices = [], sent = [];
  const window = {addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: name => listeners.delete(name), postMessage: value => notices.push(value)};
  const chrome = {runtime: {id: 'test', onMessage: {addListener() {}},
    sendMessage: message => { sent.push(message); return sendMessage(message); }}};
  const context = {window, chrome, location: {origin: 'https://meet.google.com'}, Promise};
  vm.runInNewContext(source, context);
  const pcm = data => listeners.get('message')?.({source: window, origin: context.location.origin,
    data: data || {ct: 'microphone', samples: Array(320).fill(0)}});
  return {context, listeners, notices, sent, pcm};
}
(async () => {
  const valid = setup(() => Promise.resolve({ok: true}));
  valid.pcm(); await new Promise(setImmediate); assert.equal(valid.sent.length, 1);
  valid.pcm({ct: 'microphone', samples: Array(320).fill('invalid')}); assert.equal(valid.sent.length, 1);
  valid.pcm({ct: 'translation-failed', error: 'untrusted page text'});
  await new Promise(setImmediate);
  assert.equal(valid.sent.length, 2);
  assert.equal(valid.sent[1].type, 'page-failed');
  assert.equal(valid.sent[1].error, undefined);
  valid.context.chrome.runtime = undefined;
  assert.doesNotThrow(() => valid.pcm());
  assert.equal(valid.notices.length, 1); assert.equal(valid.listeners.size, 0);
  for (const failure of [() => { throw Error('Extension context invalidated'); },
    () => Promise.reject(Error('No receiving end'))]) {
    const fixture = setup(failure);
    fixture.pcm(); await new Promise(setImmediate);
    assert.equal(fixture.notices.length, 1); assert.equal(fixture.listeners.size, 0);
    fixture.pcm(); assert.equal(fixture.sent.length, 1);
  }
  const unload = setup(() => Promise.resolve());
  unload.context.chrome = undefined;
  assert.doesNotThrow(() => unload.listeners.get('pagehide')());
  assert.equal(unload.notices.length, 1);
  console.log('Bridge forwarding, validation and runtime loss: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
