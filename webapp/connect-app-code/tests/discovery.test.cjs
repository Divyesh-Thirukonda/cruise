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

test('external registry bypasses Blob, authenticates reads and coalesces concurrent lookups', async () => {
  const saved=global.fetch, previous=process.env.MODULATE_DISCOVERY_REGISTRY_URL;
  process.env.MODULATE_DISCOVERY_REGISTRY_URL='https://modulate-discovery.example.workers.dev';
  delete require.cache[require.resolve('../server/device-registry.cjs')];
  const registry=require('../server/device-registry.cjs');
  const calls=[],origin='https://new-device.trycloudflare.com',secret='test-only';
  try {
    global.fetch=async(url,options)=>{
      calls.push(url);
      if(url.endsWith('/resolve')) {
        assert.equal(options.headers.Authorization,`Bearer ${createHmac('sha256',secret).update('modulate-discovery-registry-v1').digest('hex')}`);
        assert.equal(options.redirect,'error');
        return Response.json({origin,timestamp:Math.floor(Date.now()/1000)});
      }
      const nonce=new URL(url).searchParams.get('nonce');
      assert.ok(nonce);assert.equal(options.headers,undefined);
      return Response.json({proof:createHmac('sha256',secret).update(`modulate-discovery-v1:${nonce}`).digest('hex')});
    };
    assert.deepEqual(await Promise.all([registry.resolve(secret),registry.resolve(secret),registry.resolve(secret)]),[origin,origin,origin]);
    assert.equal(calls.length,2);
    assert.equal(await registry.resolve(secret),origin);assert.equal(calls.length,2);
  } finally {global.fetch=saved;if(previous===undefined)delete process.env.MODULATE_DISCOVERY_REGISTRY_URL;else process.env.MODULATE_DISCOVERY_REGISTRY_URL=previous;}
});
test('external registration proves tunnel first; failure recovers without cached rejection',async()=>{
  const saved=global.fetch, previous=process.env.MODULATE_DISCOVERY_REGISTRY_URL;
  process.env.MODULATE_DISCOVERY_REGISTRY_URL='https://modulate-discovery.example.workers.dev';
  delete require.cache[require.resolve('../server/device-registry.cjs')];
  const registry=require('../server/device-registry.cjs');
  const secret='test-only',origin='https://new-device.trycloudflare.com',calls=[];
  let fail=true;
  try {
    global.fetch=async(url,options)=>{
      calls.push(url);
      if(url.endsWith('/resolve'))return fail?new Response('',{status:503}):Response.json({origin});
      if(url.endsWith('/register')){assert.equal(options.headers.Authorization,undefined);return Response.json({registered:true});}
      const nonce=new URL(url).searchParams.get('nonce');
      return Response.json({proof:createHmac('sha256',secret).update(`modulate-discovery-v1:${nonce}`).digest('hex')});
    };
    await assert.rejects(registry.resolve(secret));fail=false;
    assert.equal(await registry.resolve(secret),origin);
    calls.length=0;
    const body={origin,timestamp:Math.floor(Date.now()/1000)},signature=createHmac('sha256',secret).update(`${body.timestamp}\n${origin}`).digest('hex');
    assert.deepEqual(await registry.register(body,signature,secret),{registered:true});
    assert.match(calls[0],/\/identity\?nonce=/);assert.match(calls[1],/\/register$/);
  } finally {global.fetch=saved;if(previous===undefined)delete process.env.MODULATE_DISCOVERY_REGISTRY_URL;else process.env.MODULATE_DISCOVERY_REGISTRY_URL=previous;}
});
