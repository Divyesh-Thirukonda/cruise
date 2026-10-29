'use strict';
const { test, beforeEach, after } = require('node:test');
const assert = require('node:assert/strict');
const { nextHandler } = require('../server/next-adapter.cjs');
const gateway = nextHandler(require('../api/modulate.js'));
const provider = nextHandler(require('../api/modulate-provider.js'), 1024 * 1024);

const SESSION = 's'.repeat(43), CSRF = 'a'.repeat(64);
const originalFetch = global.fetch;
const environment = { ...process.env };
let calls;
function request(action, { method = 'GET', body, headers = {}, authenticated = true } = {}) {
  return new Request(`https://modulate-connect.vercel.app/api/modulate?action=${action}`, {
    method,
    headers: {
      ...(method !== 'GET' ? { origin: 'https://modulate-connect.vercel.app', 'content-type': 'application/json', 'x-modulate-csrf': CSRF } : {}),
      cookie: `__Host-modulate_csrf=${CSRF}${authenticated ? '; __Host-modulate_session=' + SESSION : ''}`,
      ...headers,
    },
    ...(body !== undefined ? { body: typeof body === 'string' ? body : JSON.stringify(body) } : {}),
  });
}
beforeEach(() => {
  process.env.MODULATE_PUBLIC_ORIGIN = 'https://modulate-connect.vercel.app';
  process.env.MODULATE_COMPANION_URL = 'https://companion.example';
  process.env.MODULATE_REMOTE_SECRET = 'remote-test-only-'.repeat(4);
  process.env.MODULATE_CLOUD_KEY = 'cloud-test-only-'.repeat(4);
  process.env.MODULATE_ELEVENLABS_API_KEY = 'speech-test-only';
  calls = [];
  global.fetch = async (...args) => {
    calls.push(args);
    return Response.json({ connected: false, permissions: {} });
  };
});
after(() => {
  global.fetch = originalFetch;
  for (const key of Object.keys(process.env)) if (!(key in environment)) delete process.env[key];
  Object.assign(process.env, environment);
});

test('Next pairing preserves two protected cookies and omits unspecified access changes', async () => {
  global.fetch = async (...args) => {
    calls.push(args);
    return Response.json({ connected: true, token: SESSION, expires_at: Date.now() / 1000 + 600, permissions: { camera: false } });
  };
  const result = await gateway(request('session', { method: 'POST', body: { code: '01234567' }, authenticated: false }));
  assert.equal(result.status, 200);
  const cookies = result.headers.getSetCookie();
  assert.equal(cookies.length, 2);
  assert.match(cookies[0], /^__Host-modulate_session=/);
  assert.match(cookies[1], /^__Host-modulate_csrf=/);
  for (const cookie of cookies) assert.match(cookie, /HttpOnly; Secure; SameSite=Strict/);
  assert.deepEqual(JSON.parse(calls[0][1].body), { code: '01234567' });
  const data = await result.json();
  assert.equal(data.token, undefined);
  assert.deepEqual(data.permissions, { camera: false });
  assert.equal(result.headers.get('cache-control'), 'private, no-store, max-age=0');
});

test('Next route rejects duplicate action parameters without contacting the companion', async () => {
  const result = await gateway(request('state&action=session'));
  assert.equal(result.status, 400);
  assert.equal(calls.length, 0);
});

test('Next route preserves origin, CSRF, and private-state authentication checks', async () => {
  assert.equal((await gateway(request('state', { authenticated: false }))).status, 401);
  assert.equal((await gateway(request('session', { method: 'POST', body: { code: '12345678' }, headers: { origin: 'https://evil.example' } }))).status, 403);
  assert.equal((await gateway(request('session', { method: 'POST', body: { code: '12345678' }, headers: { 'x-modulate-csrf': 'wrong' } }))).status, 403);
  assert.equal(calls.length, 0);
});

test('Next route bounds body streams even without Content-Length', async () => {
  const result = await gateway(request('session', { method: 'POST', body: 'x'.repeat(256 * 1024 + 1) }));
  assert.equal(result.status, 413);
  assert.equal(result.headers.get('cache-control'), 'private, no-store, max-age=0');
  assert.equal(calls.length, 0);
});

test('Next route rejects oversized declared bodies and malformed JSON', async () => {
  assert.equal((await gateway(request('session', { method: 'POST', body: '{}', headers: { 'content-length': '999999' } }))).status, 413);
  assert.equal((await gateway(request('session', { method: 'POST', body: '{' }))).status, 400);
  assert.equal(calls.length, 0);
});

test('Next preview response retains PNG bytes and content type', async () => {
  const bytes = new Uint8Array([137, 80, 78, 71, 0, 255]);
  global.fetch = async () => new Response(bytes, { headers: { 'Content-Type': 'image/png' } });
  const result = await gateway(request('preview&candidate=1'));
  assert.equal(result.status, 200);
  assert.equal(result.headers.get('content-type'), 'image/png');
  assert.deepEqual(new Uint8Array(await result.arrayBuffer()), bytes);
});

test('Next provider response retains PCM bytes and rejects browser callers', async () => {
  const bytes = new Uint8Array([0, 0, 255, 127]);
  global.fetch = async () => new Response(bytes, { headers: { 'Content-Type': 'audio/pcm' } });
  const cloudRequest = headers => new Request('https://modulate-connect.vercel.app/api/modulate-provider?action=speech', {
    method: 'POST', headers: { authorization: `Bearer ${process.env.MODULATE_CLOUD_KEY}`, 'content-type': 'application/json', ...headers },
    body: JSON.stringify({ voice_id: 'VoiceExample123', payload: { text: 'Ready.', model_id: 'eleven_flash_v2_5' } }),
  });
  const result = await provider(cloudRequest({}));
  assert.equal(result.status, 200);
  assert.equal(result.headers.get('content-type'), 'audio/pcm');
  assert.deepEqual(new Uint8Array(await result.arrayBuffer()), bytes);
  assert.equal((await provider(cloudRequest({ origin: 'https://modulate-connect.vercel.app' }))).status, 403);
});

test('Next disconnect keeps the expiry cookie and 405 responses retain Allow', async () => {
  const result = await gateway(request('session', { method: 'DELETE' }));
  assert.equal(result.status, 200);
  assert.match(result.headers.getSetCookie()[0], /^__Host-modulate_session=;.*Max-Age=0/);
  const unsupported = await gateway(request('state', { method: 'POST', body: {} }));
  assert.equal(unsupported.status, 405);
  assert.equal(unsupported.headers.get('allow'), 'GET');
});
