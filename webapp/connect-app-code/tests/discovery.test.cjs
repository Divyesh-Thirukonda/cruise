const test = require('node:test');
const assert = require('node:assert/strict');
const { createHmac } = require('node:crypto');
const { tunnelOrigin, prove, register } = require('../server/device-registry.cjs');
test('discovery rejects arbitrary origins and old or unsigned registration', async () => {
  for (const url of ['http://localhost', 'https://a.trycloudflare.com.evil.test', 'https://a.trycloudflare.com/path', 'https://user@a.trycloudflare.com', 'https://127.0.0.1']) {
    assert.throws(() => tunnelOrigin(url));
  }
  assert.equal(tunnelOrigin('https://one-two.trycloudflare.com'), 'https://one-two.trycloudflare.com');
  await assert.rejects(register({ origin: 'https://one-two.trycloudflare.com', timestamp: 1 }, '', 'secret'));
  await assert.rejects(register({ origin: 'https://one-two.trycloudflare.com', timestamp: Math.floor(Date.now()/1000) }, '', 'secret'));
});
test('fresh challenge proves the device before a credential can be sent', async () => {
  const saved = global.fetch;
  try {
    global.fetch = async (url, options) => {
      assert.equal(options.headers, undefined);
      assert.equal(options.redirect, 'error');
      const nonce = new URL(url).searchParams.get('nonce');
      return Response.json({ proof: createHmac('sha256', 'secret').update(`modulate-discovery-v1:${nonce}`).digest('hex') });
    };
    await prove('https://one-two.trycloudflare.com', 'secret');
    await assert.rejects(prove('https://one-two.trycloudflare.com', 'wrong-secret'));
  } finally { global.fetch = saved; }
});
