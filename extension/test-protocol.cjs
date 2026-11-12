const assert = require('node:assert/strict');
const {serviceURL, localStatus, permissionOrigin} = require('./protocol.js');
assert.equal(serviceURL('https://example.org/call-translator-saas/'), 'https://example.org/call-translator-saas');
assert.equal(serviceURL('http://localhost:5086/'), 'http://localhost:5086');
assert.equal(permissionOrigin('http://localhost:5086'), 'http://localhost/*');
for (const url of ['http://public.example/', 'https://user:pass@example.org/', 'https://example.org/?token=x', 'file:///etc/passwd'])
  assert.throws(() => serviceURL(url));
assert.equal(localStatus({id:1,protocol:1,ready:false,voices:[],version:'0.1.0'}).ready, false);
assert.throws(() => localStatus({id:2,protocol:1,ready:true,voices:[]}));
assert.throws(() => localStatus({id:1,protocol:99,ready:true,voices:[]}));
console.log('Extension URL and native protocol checks passed');
