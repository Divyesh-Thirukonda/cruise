'use strict';
const { test, beforeEach, after } = require('node:test');
const assert = require('node:assert/strict');
const gateway = require('../api/modulate.js');
const provider = require('../api/modulate-provider.js');
const { boundedBytes } = require('../server/modulate-http.cjs');
const SESSION = 's'.repeat(43), CSRF = 'a'.repeat(64);
const env = { ...process.env };
const originalFetch = global.fetch;
let calls;
function response(data, status = 200, headers = { 'Content-Type': 'application/json' }) {
  return new Response(typeof data === 'object' && !(data instanceof Uint8Array) ? JSON.stringify(data) : data, { status, headers });
}
function req(action, method = 'GET', body, authenticated = true) {
  return { method, query: { action }, body, headers: {
    ...(method !== 'GET' ? { origin: 'https://divy.live', 'content-type': 'application/json', 'x-modulate-csrf': CSRF } : {}),
    cookie: `__Host-modulate_csrf=${CSRF}${authenticated ? '; __Host-modulate_session=' + SESSION : ''}`,
  } };
}
function res() {
  return { headers: {}, statusCode: 200, setHeader(key, value) { this.headers[key.toLowerCase()] = value; }, status(value) { this.statusCode = value; return this; }, json(value) { this.body = value; return this; }, send(value) { this.body = value; return this; } };
}
async function run(handler, request) { const result = res(); await handler(request, result); return result; }
function cloud(action, body) {
  return { method: 'POST', query: { action }, body, headers: { 'content-type': 'application/json', authorization: 'Bearer ' + process.env.MODULATE_CLOUD_KEY } };
}
function completion() { return { model: 'muse-spark-1.3', messages: [{ role: 'user', content: 'Hi' }], max_completion_tokens: 100, stream: false }; }
beforeEach(() => {
  process.env.MODULATE_COMPANION_URL = 'https://companion.example';
  process.env.MODULATE_REMOTE_SECRET = 'remote-test-only-'.repeat(4);
  process.env.MODULATE_CLOUD_KEY = 'cloud-test-only-'.repeat(4);
  process.env.MODULATE_META_API_KEY = 'meta-test-only';
  process.env.MODULATE_ELEVENLABS_API_KEY = 'speech-test-only';
  delete process.env.VERCEL_URL;
  calls = [];
  global.fetch = async (...args) => { calls.push(args); return response({ connected: false, permissions: {}, companion: { name: 'Modulate', online: true, platform: 'darwin' } }); };
});
after(() => { global.fetch = originalFetch; for (const key of Object.keys(process.env)) if (!(key in env)) delete process.env[key]; Object.assign(process.env, env); });

test('unpaired session reveals only metadata and provides CSRF', async () => {
  const result = await run(gateway, req('session', 'GET', undefined, false));
  assert.equal(result.statusCode, 200); assert.equal(result.body.connected, false);
  assert.equal(result.body.csrfToken, CSRF); assert.equal(result.headers['cache-control'], 'private, no-store, max-age=0');
  assert.equal(calls[0][1].headers['X-Modulate-Session'], undefined);
  assert.equal(result.headers['set-cookie'], undefined, 'a poll with a valid nonce must not write stale cookies');
});
test('private state requires opaque session, before contacting upstream', async () => {
  const result = await run(gateway, req('state', 'GET', undefined, false));
  assert.equal(result.statusCode, 401); assert.equal(calls.length, 0);
});
test('successful pairing stores token only in HttpOnly cookie and retains the valid csrf nonce', async () => {
  global.fetch = async (...args) => { calls.push(args); return response({ connected: true, token: SESSION, expires_at: Date.now() / 1000 + 28800, permissions: { system: true }, secret: 'must-not-leak' }); };
  const result = await run(gateway, req('session', 'POST', { code: '12345678', name: 'Phone', permissions: { remote_preview: false } }, false));
  assert.equal(result.statusCode, 200); assert.equal(result.body.csrfToken, CSRF);
  assert.ok(!JSON.stringify(result.body).includes(SESSION)); assert.equal(result.body.secret, undefined);
  assert.ok(result.headers['set-cookie'][0].includes(SESSION));
  assert.equal(calls[0][0], 'https://companion.example/session');
});
test('an initial session creates only a protected csrf cookie', async () => {
  const request = req('session', 'GET', undefined, false); delete request.headers.cookie;
  const result = await run(gateway, request);
  assert.equal(result.headers['set-cookie'].length, 1);
  assert.match(result.headers['set-cookie'][0], /^__Host-modulate_csrf=/);
  assert.match(result.headers['set-cookie'][0], /HttpOnly; Secure; SameSite=Strict/);
  assert.match(result.body.csrfToken, /^[a-f0-9]{64}$/);
});
test('stale unauthenticated and rejected reads cannot erase a newly paired cookie', async () => {
  global.fetch = async () => response({ connected: false, permissions: {} });
  const staleSession = await run(gateway, req('session'));
  assert.equal(staleSession.body.connected, false);
  assert.equal(staleSession.headers['set-cookie'], undefined);
  global.fetch = async () => response({ error: 'Expired browser token' }, 401);
  const staleState = await run(gateway, req('state'));
  assert.equal(staleState.statusCode, 401);
  assert.equal(staleState.headers['set-cookie'], undefined);
});
test('cross-origin pairing is rejected even with matching csrf', async () => {
  const request = req('session', 'POST', { code: '12345678' }, false); request.headers.origin = 'https://evil.example';
  assert.equal((await run(gateway, request)).statusCode, 403); assert.equal(calls.length, 0);
});
test('cross-site Fetch Metadata rejected even with spoofed origin', async () => {
  const request = req('command', 'POST', { path: '/api/cancel', payload: {} }); request.headers['sec-fetch-site'] = 'cross-site';
  assert.equal((await run(gateway, request)).statusCode, 403); assert.equal(calls.length, 0);
});
test('mutations require csrf header matching HttpOnly cookie', async () => {
  const request = req('command', 'POST', { path: '/api/cancel', payload: {} }); delete request.headers['x-modulate-csrf'];
  assert.equal((await run(gateway, request)).statusCode, 403); assert.equal(calls.length, 0);
});
test('arbitrary command URLs never reach companion', async () => {
  const result = await run(gateway, req('command', 'POST', { path: 'https://evil.example/secret', payload: {} }));
  assert.equal(result.statusCode, 400); assert.equal(calls.length, 0);
});
test('allowed command forwards fixed destination and session only', async () => {
  const result = await run(gateway, req('command', 'POST', { path: '/api/request', payload: { text: 'Make a game' }, upstream: 'https://evil.example' }));
  assert.equal(result.statusCode, 200); assert.equal(calls[0][0], 'https://companion.example/command');
  assert.deepEqual(JSON.parse(calls[0][1].body), { path: '/api/request', payload: { text: 'Make a game' } });
  assert.equal(calls[0][1].headers['X-Modulate-Session'], SESSION); assert.equal(calls[0][1].redirect, 'error');
});
test('library commands use the authenticated fixed companion route', async () => {
  const payload = { action: 'favorite', entry_id: 'd'.repeat(64), favorite: true };
  const result = await run(gateway, req('command', 'POST', { path: '/api/library', payload, upstream: 'https://evil.example' }));
  assert.equal(result.statusCode, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'https://companion.example/command');
  assert.equal(calls[0][1].method, 'POST');
  assert.deepEqual(JSON.parse(calls[0][1].body), { path: '/api/library', payload });
  assert.equal(calls[0][1].headers['X-Modulate-Session'], SESSION);
  assert.equal(calls[0][1].headers.Authorization, 'Bearer ' + process.env.MODULATE_REMOTE_SECRET);
  assert.equal(calls[0][1].redirect, 'error');
  assert.equal(result.headers['cache-control'], 'private, no-store, max-age=0');
});
test('library commands reject missing authentication, CSRF, and cross-origin callers before forwarding', async () => {
  const body = { path: '/api/library', payload: { action: 'trash', entry_id: 'd'.repeat(64) } };
  assert.equal((await run(gateway, req('command', 'POST', body, false))).statusCode, 401);
  const noCsrf = req('command', 'POST', body); delete noCsrf.headers['x-modulate-csrf'];
  assert.equal((await run(gateway, noCsrf)).statusCode, 403);
  const crossOrigin = req('command', 'POST', body); crossOrigin.headers.origin = 'https://evil.example';
  assert.equal((await run(gateway, crossOrigin)).statusCode, 403);
  const crossSite = req('command', 'POST', body); crossSite.headers['sec-fetch-site'] = 'cross-site';
  assert.equal((await run(gateway, crossSite)).statusCode, 403);
  assert.equal(calls.length, 0);
});
test('library route variants and malformed payloads cannot bypass the fixed allowlist', async () => {
  for (const path of ['/api/library/purge', '/api/library?target=other', '//evil.example/api/library', 'https://evil.example/api/library']) {
    assert.equal((await run(gateway, req('command', 'POST', { path, payload: { action: 'list' } }))).statusCode, 400);
  }
  assert.equal((await run(gateway, req('command', 'POST', { path: '/api/library', payload: [] }))).statusCode, 400);
  assert.equal(calls.length, 0);
});
test('library conflicts return the companion explanation without claiming success', async () => {
  global.fetch = async (...args) => { calls.push(args); return response({ error: 'This version is still active or needed for rollback' }, 409); };
  const result = await run(gateway, req('command', 'POST', { path: '/api/library', payload: { action: 'purge', entry_id: 'd'.repeat(64) } }));
  assert.equal(result.statusCode, 409);
  assert.equal(result.body.error, 'This version is still active or needed for rollback');
});
test('permissions reject unknown capabilities and truthy strings', async () => {
  for (const permissions of [{ shell: true }, { camera: 'yes' }]) assert.equal((await run(gateway, req('permissions', 'POST', { permissions }))).statusCode, 400);
  assert.equal(calls.length, 0);
});
test('explicit disconnect clears the browser cookie', async () => {
  global.fetch = async () => response({ connected: false, revoked: true });
  const result = await run(gateway, req('session', 'DELETE'));
  assert.equal(result.statusCode, 200);
  assert.ok(result.headers['set-cookie'].some(value => /^__Host-modulate_session=;/.test(value) && value.includes('Max-Age=0')));
});
test('preview permits png and fixed candidate selector only', async () => {
  global.fetch = async (...args) => { calls.push(args); return response(new Uint8Array([137, 80, 78, 71]), 200, { 'Content-Type': 'image/png' }); };
  const request = req('preview'); request.query.candidate = '1'; request.query.url = 'https://evil.example';
  const result = await run(gateway, request);
  assert.equal(result.headers['content-type'], 'image/png'); assert.equal(calls[0][0], 'https://companion.example/preview?candidate=1');
});
test('preview enforces companion privacy denial', async () => {
  global.fetch = async () => response({ error: 'Enable remote preview first.' }, 403);
  assert.equal((await run(gateway, req('preview'))).statusCode, 403);
});
test('origin redirects are never followed and network errors disclose no URL', async () => {
  global.fetch = async () => { throw new Error('secret https://companion.example failed'); };
  const result = await run(gateway, req('state'));
  assert.equal(result.statusCode, 502); assert.ok(!JSON.stringify(result.body).includes('companion.example'));
});
test('request bodies have bounded size', async () => {
  const result = await run(gateway, req('command', 'POST', { path: '/api/request', payload: { text: 'a'.repeat(256 * 1024) } }));
  assert.equal(result.statusCode, 413); assert.equal(calls.length, 0);
});
test('provider cannot be called using browser session cookies', async () => {
  const request = req('meta', 'POST', completion());
  assert.equal((await run(provider, request)).statusCode, 401); assert.equal(calls.length, 0);
});
test('provider rejects browser-origin request even if cloud key supplied', async () => {
  const request = cloud('meta', completion()); request.headers.origin = 'https://divy.live';
  assert.equal((await run(provider, request)).statusCode, 403); assert.equal(calls.length, 0);
});
test('Meta proxy keeps usage and sends key only to fixed provider', async () => {
  global.fetch = async (...args) => { calls.push(args); return response({ choices: [], usage: { completion_tokens: 2 } }); };
  const result = await run(provider, cloud('meta', completion()));
  assert.equal(result.body.usage.completion_tokens, 2); assert.equal(calls[0][0], 'https://api.meta.ai/v1/chat/completions');
  assert.equal(calls[0][1].headers.Authorization, 'Bearer meta-test-only'); assert.equal(calls[0][1].redirect, 'error');
});
test('Meta rejects alternate models, streaming, excess tokens and injected fields', async () => {
  for (const changes of [{ model: 'other' }, { stream: true }, { max_completion_tokens: 8193 }, { api_key: 'injected' }, { max_tokens: 10 }]) {
    assert.equal((await run(provider, cloud('meta', { ...completion(), ...changes }))).statusCode, 400);
  }
  assert.equal(calls.length, 0);
});
test('provider error bodies are discarded', async () => {
  global.fetch = async () => response({ error: 'API key secret and private user email' }, 429);
  const result = await run(provider, cloud('meta', completion()));
  assert.equal(result.statusCode, 429); assert.ok(!JSON.stringify(result.body).includes('private user'));
});
test('ElevenLabs uses fixed flash model, fixed pcm format and voice ID path', async () => {
  global.fetch = async (...args) => { calls.push(args); return response(new Uint8Array([0, 1, 2, 3]), 200, { 'Content-Type': 'audio/pcm' }); };
  const result = await run(provider, cloud('speech', { voice_id: 'CwhRBWXzGAHq8TQ4Fs17', payload: { text: 'Ready.', model_id: 'eleven_flash_v2_5' } }));
  assert.equal(result.headers['content-type'], 'audio/pcm'); assert.equal(calls[0][0], 'https://api.elevenlabs.io/v1/text-to-speech/CwhRBWXzGAHq8TQ4Fs17/stream?output_format=pcm_24000');
  assert.equal(calls[0][1].headers['xi-api-key'], 'speech-test-only');
});
test('speech rejects URL injection and unauthorized model', async () => {
  for (const body of [ { voice_id: '../voices', payload: { text: 'Hello', model_id: 'eleven_flash_v2_5' } }, { voice_id: 'CwhRBWXzGAHq8TQ4Fs17', payload: { text: 'Hello', model_id: 'other' } } ]) {
    assert.equal((await run(provider, cloud('speech', body))).statusCode, 400);
  }
  assert.equal(calls.length, 0);
});
test('streamed responses are bounded even without Content-Length', async () => {
  await assert.rejects(boundedBytes(new Response(new Uint8Array(10)), 9), error => error.status === 502);
});
test('speech rejects excessive per-utterance text and hidden controls', async () => {
  for (const text of ['a'.repeat(1201), 'Hello\u0000there']) {
    const result = await run(provider, cloud('speech', { voice_id: 'CwhRBWXzGAHq8TQ4Fs17', payload: { text, model_id: 'eleven_flash_v2_5' } }));
    assert.equal(result.statusCode, 400);
  }
  assert.equal(calls.length, 0);
});
test('speech rejects HTML, empty audio and odd PCM byte counts', async () => {
  for (const [bytes, mime] of [[new Uint8Array([1, 2]), 'text/html'], [new Uint8Array(), 'audio/pcm'], [new Uint8Array([1]), 'audio/pcm']]) {
    global.fetch = async () => response(bytes, 200, { 'Content-Type': mime });
    const result = await run(provider, cloud('speech', { voice_id: 'CwhRBWXzGAHq8TQ4Fs17', payload: { text: 'Ready', model_id: 'eleven_flash_v2_5' } }));
    assert.equal(result.statusCode, 502);
  }
});
