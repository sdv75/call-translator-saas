const assert = require('node:assert/strict');
const vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'native-client.js'), 'utf8');
function fixture() {
  let message, disconnected;
  const sent = [], port = {postMessage: value => sent.push(value), disconnect() {},
    onMessage: {addListener: fn => message = fn}, onDisconnect: {addListener: fn => disconnected = fn}};
  const runtime = {connectNative: () => port};
  const context = {setTimeout, clearTimeout, atob: value => Buffer.from(value, 'base64').toString('binary')};
  vm.runInNewContext(source, context);
  return {client: new context.NativePiperClient(runtime), sent, reply: value => message(value), disconnect: () => disconnected()};
}
(async () => {
  const f = fixture(), initialized = f.client.init();
  f.reply({id: 1, type: 'ready', version: 1, voices: ['ru', 'en']});
  await initialized;
  const rendered = f.client.synthesize('Hello', 'en');
  await new Promise(setImmediate);
  const audio = Buffer.concat([Buffer.from('RIFF'), Buffer.alloc(50)]);
  f.reply({id: 2, type: 'audio-chunk', index: 0, data: audio.toString('base64')});
  f.reply({id: 2, type: 'audio-end', chunks: 1, bytes: audio.length, synthesisMs: 10});
  assert.equal((await rendered).audio, audio.toString('base64'));
  const interrupted = f.client.synthesize('Another', 'en');
  await new Promise(setImmediate);
  f.disconnect();
  await assert.rejects(interrupted, /подключить/);
  const failed = fixture(), waiting = failed.client.init();
  failed.disconnect(); await assert.rejects(waiting, /Установите/);
  const invalid = fixture(), init = invalid.client.init();
  invalid.reply({id: 1, type: 'ready', version: 1, voices: ['ru', 'en']}); await init;
  const wrongOrder = invalid.client.synthesize('test', 'en'); await new Promise(setImmediate);
  invalid.reply({id: 2, type: 'audio-chunk', index: 1, data: 'AAAA'});
  await assert.rejects(wrongOrder, /Некорректный/);
  const old = fixture(), oldInit = old.client.init();
  old.reply({id: 1, type: 'ready', version: 1, voices: ['ru', 'en']}); await oldInit;
  await assert.rejects(old.client.synthesize('Привіт', 'uk'), /Обновите/);
  old.client.close();
  const uk = fixture(), ukInit = uk.client.init();
  uk.reply({id: 1, type: 'ready', version: 1, voices: ['ru', 'en', 'uk']}); await ukInit;
  const ukAudio = uk.client.synthesize('Привіт', 'uk'); await new Promise(setImmediate);
  assert.equal(uk.sent.at(-1).language, 'uk');
  uk.reply({id: 2, type: 'audio-chunk', index: 0, data: audio.toString('base64')});
  uk.reply({id: 2, type: 'audio-end', chunks: 1, bytes: audio.length, synthesisMs: 10});
  assert.equal((await ukAudio).audio, audio.toString('base64')); uk.client.close();
  console.log('Native messaging audio, disconnect cleanup, missing host and chunk validation: PASS');
})().catch(error => {console.error(error); process.exitCode = 1;});
