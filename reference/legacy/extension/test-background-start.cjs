const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
function fixture(pageError) {
  let listener, hasOffscreen = false, resolveVoice, rejectVoice;
  const data = {}, stages = [], calls = [], sessions = new Map();
  const event = () => ({addListener() {}});
  class Native {
    init() { return this.ready ||= new Promise((resolve, reject) => { resolveVoice = resolve; rejectVoice = reject; }); }
    close() { rejectVoice?.(Error('Native closed')); this.ready = null; }
  }
  const chrome = {
    runtime: {getURL: name => 'chrome-extension://test/' + name,
      onMessage: {addListener: fn => { listener = fn; }}, onStartup: event(), onInstalled: event(),
      async sendMessage(message) {
        calls.push(message.type);
        if (message.type === 'start') { assert.equal(message.streamId, 'fresh-stream'); return {ok: true}; }
        return {ok: true, complete: true};
      }},
    storage: {onChanged: {addListener() {}}, local: {
      async get(keys) { return typeof keys === 'string' ? {[keys]: data[keys]} : Object.fromEntries(keys.map(key => [key, data[key]])); },
      async set(values) { Object.assign(data, values); if (values.translationState) stages.push(values.translationState.phase); },
      async remove(keys) { for (const key of Array.isArray(keys) ? keys : [keys]) delete data[key]; }
    }},
    offscreen: {async hasDocument() { return hasOffscreen; }, async createDocument() { hasOffscreen = true; }, async closeDocument() { hasOffscreen = false; }},
    tabs: {async sendMessage() { return {ok: true}; }, onRemoved: event()},
    scripting: {async executeScript({args}) { calls.push('page-' + args[0]); return [{result: args[0] === 'start' && pageError ? {error: pageError} : {ok: true}}]; }},
    downloads: {async download() { return 1; }, onChanged: event(), async search() { return []; }}
  };
  const context = {chrome, importScripts() {}, NativePiperClient: Native, Date,
    crypto: {randomUUID: () => 'session-id'},
    CTjournal: {async saveSession(value) { sessions.set(value.id, value); }, async session(id) { return sessions.get(id); }, async entries() { return []; }},
    CTtranscript: {html: () => 'test', filename: () => '2026-11-03_19-37-14.html'}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'background.js'), 'utf8'), context);
  const request = message => new Promise(resolve => listener(message, {url: chrome.runtime.getURL('popup.html')}, resolve));
  const start = () => request({type: 'start', tabId: 42, source: 'ru', language: 'uk', tts: 'client', streamId: 'fresh-stream'});
  return {request, start, calls, stages, ready: voices => resolveVoice({voices})};
}
async function until(test) {
  for (let i = 0; i < 100 && !test(); i++) await new Promise(setImmediate);
  assert(test(), 'Background startup did not reach the expected stage');
}
(async () => {
  const f = fixture();
  assert.equal((await f.request({type: 'get-state'})).phase, 'stopped');
  const starting = f.start();
  await until(() => f.stages.includes('preparing'));
  assert(f.calls.includes('start') && f.calls.includes('page-start'));
  assert.equal((await f.request({type: 'get-state'})).phase, 'preparing');
  assert(!f.stages.includes('running'));
  // No popup code runs after this point; the background must finish itself.
  f.ready(['ru', 'en', 'uk']);
  assert.equal((await starting).ok, true);
  assert.equal((await f.request({type: 'get-state'})).phase, 'running');
  await f.request({type: 'stop'});
  assert.equal((await f.request({type: 'get-state'})).phase, 'stopped');

  const broken = fixture('Meet microphone failed');
  const failed = await broken.start();
  assert.equal(failed.error, 'Meet microphone failed');
  assert.equal((await broken.request({type: 'get-state'})).phase, 'error');
  assert(!broken.stages.includes('running'));

  const cancelled = fixture();
  const pending = cancelled.start(); await until(() => cancelled.stages.includes('preparing'));
  await cancelled.request({type: 'stop'});
  assert.equal((await pending).cancelled, true);
  assert.equal((await cancelled.request({type: 'get-state'})).phase, 'stopped');
  assert(!cancelled.stages.includes('running'));

  const format = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'transcript-format.js'), 'utf8'), format);
  const filename = format.CTtranscript.filename({id: 'MUST-NOT-APPEAR', started_at: new Date(2026, 10, 3, 19, 37, 14).getTime()});
  assert.equal(filename.split('/').at(-1), '2026-11-03_19-37-14.html');
  console.log('Background-owned startup, truthful running state, failure, cancellation and date/time-only filenames: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
