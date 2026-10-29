'use strict';
const { timingSafeEqual } = require('node:crypto');

class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
function secureEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  const left = Buffer.from(a), right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}
function noStore(res) {
  res.setHeader('Cache-Control', 'private, no-store, max-age=0');
  res.setHeader('CDN-Cache-Control', 'no-store');
  res.setHeader('Vercel-CDN-Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.setHeader('X-Frame-Options', 'DENY');
}
function objectBody(req, maximum = 256 * 1024) {
  if (String(req.headers['content-type'] || '').split(';')[0].trim() !== 'application/json') {
    throw new HttpError(415, 'Send an application/json request.');
  }
  const length = Number(req.headers['content-length']);
  if (Number.isFinite(length) && length > maximum) throw new HttpError(413, 'Request is too large.');
  let body = req.body;
  try {
    if (Buffer.isBuffer(body)) body = body.toString('utf8');
    if (typeof body === 'string') {
      if (Buffer.byteLength(body) > maximum) throw new HttpError(413, 'Request is too large.');
      body = JSON.parse(body);
    }
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('shape');
    if (Buffer.byteLength(JSON.stringify(body)) > maximum) throw new HttpError(413, 'Request is too large.');
  } catch (error) {
    if (error instanceof HttpError) throw error;
    throw new HttpError(400, 'Expected a JSON object.');
  }
  return body;
}
async function boundedBytes(response, maximum) {
  const length = Number(response.headers.get('content-length'));
  if (Number.isFinite(length) && length > maximum) throw new HttpError(502, 'Response is too large.');
  const reader = response.body?.getReader();
  if (!reader) return Buffer.alloc(0);
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maximum) throw new HttpError(502, 'Response is too large.');
      chunks.push(Buffer.from(value));
    }
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  }
  return Buffer.concat(chunks, size);
}
function queryAction(req, allowed) {
  const action = req.query?.action;
  if (typeof action !== 'string' || !allowed.includes(action)) throw new HttpError(400, 'Unknown action.');
  return action;
}
function fail(res, error, fallback = 'The service is temporarily unavailable. Try again shortly.') {
  const status = error instanceof HttpError ? error.status : 502;
  return res.status(status).json({ error: error instanceof HttpError ? error.message : fallback });
}
module.exports = { HttpError, secureEqual, noStore, objectBody, boundedBytes, queryAction, fail };
