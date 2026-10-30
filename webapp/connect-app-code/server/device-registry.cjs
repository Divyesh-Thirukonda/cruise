'use strict';
const { createHmac, randomBytes } = require('node:crypto');
const { HttpError, secureEqual, boundedBytes } = require('./modulate-http.cjs');
const PATH = 'modulate/discovery.json';
let cached;
function tunnelOrigin(value) {
  if (typeof value !== 'string' || !/^https:\/\/[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com$/.test(value)) {
    throw new HttpError(400, 'Expected a Modulate Quick Tunnel origin.');
  }
  return value;
}
async function prove(origin, secret) {
  const nonce = randomBytes(32).toString('hex');
  const response = await fetch(`${origin}/identity?nonce=${nonce}`, { redirect: 'error', signal: AbortSignal.timeout(8000) });
  const body = JSON.parse((await boundedBytes(response, 1024)).toString());
  const expected = createHmac('sha256', secret).update(`modulate-discovery-v1:${nonce}`).digest('hex');
  if (!response.ok || !secureEqual(body.proof, expected)) throw new HttpError(503, 'The device identity could not be verified.');
}
async function read() {
  const { get } = require('@vercel/blob');
  const result = await get(PATH, { access: 'private', useCache: false });
  if (!result) return null;
  const value = JSON.parse((await boundedBytes(new Response(result.stream), 2048)).toString());
  return { value, etag: result.blob.etag };
}
async function stage(name, operation) {
  try { return await operation(); }
  catch (error) {
    // Never log request headers, credentials, URLs or provider error bodies.
    console.error('Device discovery stage failed:', name, error?.constructor?.name);
    throw error;
  }
}
async function register(body, signature, secret) {
  const origin = tunnelOrigin(body.origin);
  if (!Number.isSafeInteger(body.timestamp) || Math.abs(Date.now() / 1000 - body.timestamp) > 120) throw new HttpError(401, 'Expired device registration.');
  const expected = createHmac('sha256', secret).update(`${body.timestamp}\n${origin}`).digest('hex');
  if (!secureEqual(signature, expected)) throw new HttpError(401, 'Device authentication required.');
  // Prove possession before sending any gateway credential to a new hostname.
  await stage('identity', () => prove(origin, secret));
  const current = await stage('read', read);
  if (current && current.value.timestamp > body.timestamp) throw new HttpError(409, 'A newer device registration exists.');
  if (current?.value.origin !== origin) {
    const { put } = require('@vercel/blob');
    await stage('save', () => put(PATH, JSON.stringify({ origin, timestamp: body.timestamp }), {
      access: 'private', addRandomSuffix: false, allowOverwrite: Boolean(current),
      contentType: 'application/json', ...(current ? { ifMatch: current.etag } : {}),
    }));
  }
  cached = { origin, until: Date.now() + 30000 };
  return { registered: true };
}
async function resolve(secret, force = false) {
  if (!force && cached && cached.until > Date.now()) return cached.origin;
  const record = await read();
  if (!record) throw new HttpError(503, 'Modulate is reconnecting. Keep it powered and on Wi-Fi.');
  const origin = tunnelOrigin(record.value.origin);
  await prove(origin, secret);
  cached = { origin, until: Date.now() + 30000 };
  return origin;
}
module.exports = { tunnelOrigin, prove, register, resolve };
