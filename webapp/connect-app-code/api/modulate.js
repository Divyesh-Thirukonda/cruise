'use strict';
const { randomBytes } = require('node:crypto');
const { HttpError, secureEqual, noStore, objectBody, boundedBytes, queryAction, fail } = require('../server/modulate-http.cjs');

const SESSION_COOKIE = '__Host-modulate_session';
const CSRF_COOKIE = '__Host-modulate_csrf';
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const CSRF = /^[a-f0-9]{64}$/;
const PERMISSIONS = ['computer', 'system', 'camera', 'audio', 'voice', 'speaker', 'hardware', 'remote_preview'];
const COMMANDS = new Set([
  '/api/request', '/api/context/clear', '/api/hardware/confirm', '/api/hardware/cancel',
  '/api/cancel', '/api/draft', '/api/computer', '/api/audio/stop', '/api/camera/stop',
  '/api/computer/approval', '/api/response/dismiss', '/api/speaker', '/api/pairing',
  '/api/revoke', '/api/rollback', '/api/wake', '/api/library',
]);
const METHODS = { session: ['GET', 'POST', 'DELETE'], state: ['GET'], command: ['POST'], preview: ['GET'], permissions: ['POST'] };

function cookies(req) {
  const result = {};
  for (const part of String(req.headers.cookie || '').split(';')) {
    const index = part.indexOf('=');
    if (index > 0) result[part.slice(0, index).trim()] = part.slice(index + 1).trim();
  }
  return result;
}
function cookie(name, value, maxAge) {
  return `${name}=${value}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${maxAge}`;
}
function permissionShape(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !PERMISSIONS.includes(key) || typeof value[key] !== 'boolean')) {
    throw new HttpError(400, 'Permissions must contain supported on/off switches.');
  }
  return value;
}
function sameOrigin(req) {
  let origin;
  try { origin = new URL(req.headers.origin); } catch { throw new HttpError(403, 'Open this request from Modulate Connect.'); }
  const allowed = [process.env.MODULATE_PUBLIC_ORIGIN || 'https://modulate-connect.vercel.app'];
  if (process.env.VERCEL_URL) allowed.push(`https://${process.env.VERCEL_URL}`);
  if (origin.origin !== req.headers.origin || !allowed.includes(origin.origin) || origin.protocol !== 'https:') {
    throw new HttpError(403, 'Open this request from Modulate Connect.');
  }
  const site = req.headers['sec-fetch-site'];
  if (site && site !== 'same-origin' && site !== 'none') throw new HttpError(403, 'Cross-site requests are not allowed.');
}
function config() {
  let url;
  try { url = new URL(process.env.MODULATE_COMPANION_URL); } catch { throw new HttpError(503, 'The companion connection is not configured yet.'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new HttpError(503, 'The companion connection is not configured correctly.');
  }
  const secret = process.env.MODULATE_REMOTE_SECRET;
  if (!secret || secret.length < 32) throw new HttpError(503, 'The companion connection is not configured yet.');
  return { origin: url.origin, secret };
}
async function forward(path, method, body, session) {
  const { origin, secret } = config();
  const headers = { Authorization: `Bearer ${secret}`, Accept: path.startsWith('/preview') ? 'image/png' : 'application/json' };
  if (session) headers['X-Modulate-Session'] = session;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(origin + path, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    redirect: 'error', signal: AbortSignal.timeout(20000),
  });
  const bytes = await boundedBytes(response, path.startsWith('/preview') ? 1024 * 1024 : 4 * 1024 * 1024);
  return { response, bytes };
}
function publicSession(data) {
  // Explicit projection: the companion's bearer token must never reach browser JavaScript.
  return {
    connected: data.connected === true,
    companion: data.companion && { name: String(data.companion.name || 'Modulate companion').slice(0, 80), online: data.companion.online === true, platform: String(data.companion.platform || '').slice(0, 30) },
    permissions: data.permissions ? permissionShape(data.permissions) : {},
    expires_at: Number.isFinite(data.expires_at) ? data.expires_at : null,
    name: typeof data.name === 'string' ? data.name.slice(0, 80) : undefined,
  };
}

async function handler(req, res) {
  noStore(res);
  res.setHeader('Vary', 'Cookie');
  try {
    const action = queryAction(req, Object.keys(METHODS));
    if (!METHODS[action].includes(req.method)) {
      res.setHeader('Allow', METHODS[action].join(', '));
      throw new HttpError(405, 'Method not allowed.');
    }
    const jar = cookies(req);
    const session = TOKEN.test(jar[SESSION_COOKIE] || '') ? jar[SESSION_COOKIE] : null;
    let csrf = CSRF.test(jar[CSRF_COOKIE] || '') ? jar[CSRF_COOKIE] : null;
    const setCookies = [];
    if (req.method !== 'GET') {
      sameOrigin(req);
      if (!csrf || !secureEqual(csrf, req.headers['x-modulate-csrf'])) throw new HttpError(403, 'Refresh Connect before trying again.');
    }
    if (action !== 'session' && !session) throw new HttpError(401, 'Connect this browser using the code on your companion.');
    let path = '/' + action;
    let body;
    if (req.method === 'POST') {
      body = objectBody(req);
      if (action === 'session') {
        if (typeof body.code !== 'string' || !/^\d{8}$/.test(body.code)) throw new HttpError(400, 'Enter the eight-digit connection code.');
        if (body.name !== undefined && (typeof body.name !== 'string' || body.name.length < 1 || body.name.length > 80 || /[\x00-\x1f\x7f]/.test(body.name))) throw new HttpError(400, 'Choose a short name for this browser.');
        body = { code: body.code, ...(body.name ? { name: body.name } : {}), ...(body.permissions === undefined ? {} : { permissions: permissionShape(body.permissions) }) };
      } else if (action === 'permissions') {
        body = { permissions: permissionShape(body.permissions) };
      } else if (action === 'command') {
        if (!COMMANDS.has(body.path) || !body.payload || typeof body.payload !== 'object' || Array.isArray(body.payload)) throw new HttpError(400, 'Unknown companion command.');
        body = { path: body.path, payload: body.payload };
      }
    }
    if (action === 'preview' && req.query.candidate === '1') path += '?candidate=1';
    const { response, bytes } = await forward(path, req.method, body, session);
    let data;
    if (action !== 'preview' || !response.ok) {
      try { data = JSON.parse(bytes.toString('utf8')); } catch { throw new HttpError(502, 'The companion returned an invalid response.'); }
    }
    if (!response.ok) {
      // Reads may finish after a new pairing in another request or tab. An
      // invalid old token must not erase a newer HttpOnly session cookie.
      const message = typeof data?.error === 'string' ? data.error.slice(0, 500) : 'The companion could not complete this action.';
      throw new HttpError([400, 401, 403, 404, 409, 413, 429, 503].includes(response.status) ? response.status : 502, message);
    }
    if (action === 'session') {
      if (req.method === 'POST') {
        if (!TOKEN.test(data.token || '') || data.connected !== true) throw new HttpError(502, 'The companion could not complete pairing.');
        const seconds = Math.max(0, Math.min(28800, Math.floor(Number(data.expires_at) - Date.now() / 1000)));
        if (!seconds) throw new HttpError(502, 'The connection has already expired.');
        setCookies.push(cookie(SESSION_COOKIE, data.token, seconds));
        // A CSRF nonce is not the authentication grant. Keep the existing
        // nonce so concurrent session polls cannot restore an obsolete one.
        setCookies.push(cookie(CSRF_COOKIE, csrf, 28800));
      } else if (req.method === 'DELETE') {
        setCookies.push(cookie(SESSION_COOKIE, '', 0));
      }
      if (!csrf) {
        csrf = randomBytes(32).toString('hex');
        setCookies.push(cookie(CSRF_COOKIE, csrf, 28800));
      }
      if (setCookies.length) res.setHeader('Set-Cookie', setCookies);
      return res.status(200).json({ ...publicSession(data), csrfToken: csrf });
    }
    if (action === 'preview') {
      if (!String(response.headers.get('content-type') || '').startsWith('image/png')) throw new HttpError(502, 'The companion returned an invalid preview.');
      res.setHeader('Content-Type', 'image/png');
      return res.status(200).send(bytes);
    }
    return res.status(200).json(data);
  } catch (error) {
    return fail(res, error, 'The companion is offline. Keep Modulate Studio and its connection running on your Mac.');
  }
}
module.exports = handler;
