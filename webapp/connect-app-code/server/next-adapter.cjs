'use strict';
const { HttpError, noStore, fail } = require('./modulate-http.cjs');

async function readBody(request, maximum) {
  const declared = Number(request.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > maximum) throw new HttpError(413, 'Request is too large.');
  if (!request.body) return Buffer.alloc(0);
  const reader = request.body.getReader();
  let length = 0;
  const chunks = [];
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > maximum) throw new HttpError(413, 'Request is too large.');
      chunks.push(Buffer.from(value));
    }
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  }
  return Buffer.concat(chunks, length);
}

function queryValues(url) {
  const query = Object.create(null);
  for (const key of new Set(url.searchParams.keys())) {
    const values = url.searchParams.getAll(key);
    query[key] = values.length === 1 ? values[0] : values;
  }
  return query;
}

// Preserve the reviewed gateway handlers and their exact validation, cookies,
// revocation, provider auth, no-store headers, and binary payload contracts.
function nextHandler(handler, maximum = 256 * 1024) {
  return async function route(request) {
    const headers = new Headers();
    let status = 200;
    let payload = null;
    const response = {
      setHeader(name, value) {
        headers.delete(name);
        for (const item of Array.isArray(value) ? value : [value]) headers.append(name, String(item));
      },
      getHeader(name) { return headers.get(name); },
      status(code) { status = code; return this; },
      json(value) { headers.set('Content-Type', 'application/json; charset=utf-8'); payload = JSON.stringify(value); return this; },
      send(value) { payload = value; return this; },
      end(value = null) { payload = value; return this; },
    };
    try {
      const req = {
        method: request.method,
        url: request.url,
        headers: Object.fromEntries(request.headers),
        query: queryValues(new URL(request.url)),
        body: ['GET', 'HEAD'].includes(request.method) ? undefined : await readBody(request, maximum),
      };
      await handler(req, response);
    } catch (error) {
      noStore(response);
      fail(response, error);
    }
    return new Response(request.method === 'HEAD' ? null : payload, { status, headers });
  };
}

module.exports = { nextHandler };
