const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const {median, summaries, report} = await import('./tts-test-common.mjs');
  assert.equal(median([]), null); assert.equal(median([3, 1, 2, 4]), 2.5);
  const rows = [];
  for (const language of ['ru', 'en']) for (const kind of ['short', 'long']) {
    rows.push({language, kind, benchmark: true, cold: true, ratio: 100});
    for (let i = 0; i < 5; i++) rows.push({language, kind, benchmark: true, cold: false,
      ratio: .2, text: 'PRIVATE_INPUT', wav: 'PRIVATE_AUDIO'});
  }
  assert(summaries(rows).every(summary => summary.pass));
  assert(summaries(rows.slice(0, -1)).some(summary => !summary.pass));
  const exported = JSON.stringify(report(rows, [{language: 'ru', ms: 123, cached: false, url: 'PRIVATE_URL'}],
    {userAgent: 'test', hardwareConcurrency: 4, token: 'PRIVATE_TOKEN'}));
  assert(!exported.includes('PRIVATE_'));
  const worker = fs.readFileSync(path.join(__dirname, 'tts-test-worker.js'), 'utf8');
  assert(!worker.includes('connection.json'));
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, 'manifest.json'), 'utf8'));
  assert(manifest.content_security_policy.extension_pages.includes("'wasm-unsafe-eval'"));
  assert(!manifest.content_security_policy.extension_pages.includes("'unsafe-eval'"));
  const vendor = path.join(__dirname, 'vendor/browser-tts');
  const artifacts = JSON.parse(fs.readFileSync(path.join(vendor, 'artifacts.json'), 'utf8'));
  for (const [name, recorded] of Object.entries(artifacts.artifacts)) {
    const bytes = fs.readFileSync(path.join(vendor, name));
    assert.equal(bytes.length, recorded.bytes);
    assert.equal(require('node:crypto').createHash('sha256').update(bytes).digest('hex'), recorded.sha256);
  }
  console.log('Benchmark grouping, cold-run exclusion, report privacy and WASM policy: PASS');
})().catch(error => {console.error(error); process.exitCode = 1;});
