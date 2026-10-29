'use strict';
const { HttpError, secureEqual, noStore, objectBody, boundedBytes, queryAction, fail } = require('../server/modulate-http.cjs');

const META_FIELDS = new Set(['model', 'messages', 'tools', 'tool_choice', 'stream', 'max_completion_tokens', 'max_tokens', 'temperature', 'reasoning_effort']);
function metaPayload(body) {
  if (Object.keys(body).some(key => !META_FIELDS.has(key)) || body.model !== 'muse-spark-1.3' || body.stream !== false) {
    throw new HttpError(400, 'Unsupported model request.');
  }
  const limit = body.max_completion_tokens ?? body.max_tokens;
  if ((body.max_completion_tokens !== undefined && body.max_tokens !== undefined) || !Number.isInteger(limit) || limit < 1 || limit > 8192) {
    throw new HttpError(400, 'A completion limit from 1 to 8192 is required.');
  }
  if (!Array.isArray(body.messages) || !body.messages.length || body.messages.length > 200 || (body.tools !== undefined && (!Array.isArray(body.tools) || body.tools.length > 64))) {
    throw new HttpError(400, 'Invalid conversation.');
  }
  if (body.temperature !== undefined && (typeof body.temperature !== 'number' || body.temperature < 0 || body.temperature > 2 || !Number.isFinite(body.temperature))) {
    throw new HttpError(400, 'Invalid temperature.');
  }
  if (body.reasoning_effort !== undefined && !['none', 'minimal', 'low', 'medium', 'high', 'max'].includes(body.reasoning_effort)) {
    throw new HttpError(400, 'Invalid reasoning effort.');
  }
  return body;
}
function speechRequest(body) {
  if (Object.keys(body).some(key => !['voice_id', 'payload'].includes(key)) || typeof body.voice_id !== 'string' || !/^[A-Za-z0-9]{10,64}$/.test(body.voice_id)) throw new HttpError(400, 'Invalid speech voice.');
  const payload = body.payload;
  if (!payload || typeof payload !== 'object' || Array.isArray(payload) || Object.keys(payload).some(key => !['text', 'model_id'].includes(key)) || payload.model_id !== 'eleven_flash_v2_5' || typeof payload.text !== 'string' || payload.text.trim().length < 1 || payload.text.length > 1200 || Buffer.byteLength(payload.text, 'utf8') > 4800 || /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(payload.text)) {
    throw new HttpError(400, 'Invalid speech request.');
  }
  return payload;
}

async function handler(req, res) {
  noStore(res);
  try {
    if (req.method !== 'POST') {
      res.setHeader('Allow', 'POST');
      throw new HttpError(405, 'Method not allowed.');
    }
    const secret = process.env.MODULATE_CLOUD_KEY;
    if (!secret || secret.length < 32) throw new HttpError(503, 'Cloud services are not configured.');
    if (!secureEqual(req.headers.authorization, `Bearer ${secret}`)) throw new HttpError(401, 'Companion authentication required.');
    // This endpoint is only called by the trusted companion after its durable spend reservation.
    // Browser cookies are deliberately not accepted; the cloud key never leaves the companion.
    if (req.headers.origin || req.headers['sec-fetch-site']) throw new HttpError(403, 'Only the companion can call cloud services.');
    const action = queryAction(req, ['meta', 'speech']);
    const body = objectBody(req, 1024 * 1024);
    let url, payload, headers;
    if (action === 'meta') {
      payload = metaPayload(body);
      if (!process.env.MODULATE_META_API_KEY) throw new HttpError(503, 'Meta is not configured.');
      url = 'https://api.meta.ai/v1/chat/completions';
      headers = { Authorization: `Bearer ${process.env.MODULATE_META_API_KEY}`, Accept: 'application/json' };
    } else {
      payload = speechRequest(body);
      if (!process.env.MODULATE_ELEVENLABS_API_KEY) throw new HttpError(503, 'Speech is not configured.');
      url = `https://api.elevenlabs.io/v1/text-to-speech/${body.voice_id}/stream?output_format=pcm_24000`;
      headers = { 'xi-api-key': process.env.MODULATE_ELEVENLABS_API_KEY, Accept: 'audio/pcm' };
    }
    const response = await fetch(url, {
      method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), redirect: 'error', signal: AbortSignal.timeout(240000),
    });
    if (!response.ok) {
      await response.body?.cancel();
      // Provider bodies can contain request text or account details. Return only the status category.
      throw new HttpError([400, 401, 403, 429, 503].includes(response.status) ? response.status : 502,
        `${action === 'meta' ? 'Meta' : 'Speech'} provider could not complete the request (${response.status}).`);
    }
    const bytes = await boundedBytes(response, action === 'meta' ? 1024 * 1024 : 24000 * 2 * 90);
    if (action === 'meta') {
      let result;
      try { result = JSON.parse(bytes.toString('utf8')); } catch { throw new HttpError(502, 'Meta returned an invalid response.'); }
      return res.status(200).json(result);
    }
    const mime = String(response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
    if (!['audio/pcm', 'audio/x-pcm', 'audio/raw', 'application/octet-stream'].includes(mime) || !bytes.length || bytes.length % 2 !== 0) {
      throw new HttpError(502, 'Speech provider returned invalid PCM audio.');
    }
    res.setHeader('Content-Type', 'audio/pcm');
    return res.status(200).send(bytes);
  } catch (error) { return fail(res, error, 'The cloud provider could not complete the request.'); }
}
module.exports = handler;
