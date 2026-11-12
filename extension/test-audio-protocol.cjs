const assert=require('node:assert/strict');
require('./protocol.js');
const {frame,chunks,websocketURL}=require('./audio-protocol.js');
assert.equal(websocketURL('https://example.org/service'),'wss://example.org/service/ws');
assert.equal(websocketURL('http://localhost:5086'),'ws://localhost:5086/ws');
const samples=Array(320).fill(0);samples[0]=-32768;samples[1]=32767;
const data=new DataView(frame('incoming',samples));
assert.equal(data.byteLength,641);assert.equal(data.getUint8(0),1);
assert.equal(data.getInt16(1,true),-32768);assert.equal(data.getInt16(3,true),32767);
assert.throws(()=>frame('outgoing',[0]));assert.throws(()=>frame('other',samples));
const text='Я🙂'.repeat(2000),parts=chunks(text);
assert.equal(parts.join(''),text);assert(parts.every(part=>part.length<=1400));
assert(parts.every(part=>!/[\uD800-\uDBFF]$/.test(part)));
const {speechChunks}=require('./audio-protocol.js');
for(const sample of ['Первая фраза. Остання фраза перевірки: усе збережено.','Hello world! Next sentence. '+text]){
  const spoken=speechChunks(sample);assert.equal(spoken.join(''),sample);assert(spoken.length>1);
  assert(spoken.every(part=>part.length<=240&&!/[\uD800-\uDBFF]$/.test(part)));
}
const format=require('./transcript-format.js');
const html=format.html({started_at:0},[{direction:'incoming',original:'<script>alert(1)</script>',text:'<img onerror=x>'}]);
assert(!html.includes('<script>'));assert(!html.includes('<img'));assert(html.includes('&lt;script&gt;'));
assert(/^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.html$/.test(format.filename(Date.now())));
console.log('Audio protocol and private transcript export: bounds, endian, Unicode and escaping passed');
