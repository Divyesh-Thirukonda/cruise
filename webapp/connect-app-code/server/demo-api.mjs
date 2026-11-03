import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';
import { getQuickJS } from 'quickjs-emscripten';
import { generateApp, MODEL } from './demo-generation.mjs';
import { MODULE_IDS, validatePackage } from '../shared/demo-runtime.mjs';
const cookieName = 'modulate_demo';
const json = (data, status = 200, headers = {}) =>
  Response.json(data, { status, headers: { 'Cache-Control': 'private, no-store', ...headers } });
const equal = (a, b) =>
  typeof a === 'string' &&
  typeof b === 'string' &&
  Buffer.byteLength(a) === Buffer.byteLength(b) &&
  timingSafeEqual(Buffer.from(a), Buffer.from(b));
export function demoHandler(env = process.env, fetchImpl = fetch) {
  const hmac = (text) =>
    createHmac('sha256', env.MODULATE_REMOTE_SECRET).update(text).digest('hex');
  const budget = async (action, body) => {
    const url = env.MODULATE_DISCOVERY_REGISTRY_URL;
    if (!url || !/^https:\/\/[a-z0-9.-]+\.workers\.dev$/.test(url))
      throw Error('The demo allowance is not configured.');
    const res = await fetchImpl(`${url}/demo-budget/${action}`, {
      method: 'POST',
      redirect: 'error',
      signal: AbortSignal.timeout(10000),
      headers: {
        Authorization: `Bearer ${hmac('modulate-discovery-registry-v1')}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw Error(data.error || 'The demo allowance is unavailable.');
    return data;
  };
  return async (request) => {
    if (!env.MODULATE_META_API_KEY || !env.MODULATE_REMOTE_SECRET)
      return json({ error: 'Live generation is not configured.' }, 503);
    const now = Math.floor(Date.now() / 1000),
      secure = new URL(request.url).protocol === 'https:';
    if (request.method === 'GET') {
      try {
        await getQuickJS();
      } catch {
        return json({ error: 'The app verifier is unavailable. Please try again later.' }, 503);
      }
      let token = request.headers
        .get('cookie')
        ?.split(';')
        .map((s) => s.trim())
        .find((s) => s.startsWith(cookieName + '='))
        ?.slice(cookieName.length + 1);
      const valid = (value) => {
        const [id, exp, sig] = String(value || '').split('.');
        return (
          /^[a-f0-9-]{36}$/.test(id) &&
          Number(exp) > now &&
          Number(exp) <= now + 28800 &&
          equal(sig, hmac(`${id}.${exp}`))
        );
      };
      if (!valid(token)) {
        const raw = `${randomUUID()}.${now + 28800}`;
        token = `${raw}.${hmac(raw)}`;
      }
      return json({ csrf: hmac(`csrf:${token}`), model: MODEL }, 200, {
        'Set-Cookie': `${cookieName}=${token}; Path=/api/demo; HttpOnly; SameSite=Strict; Max-Age=28800${secure ? '; Secure' : ''}`,
      });
    }
    if (request.method !== 'POST') return json({ error: 'Method not allowed' }, 405);
    const allowed = env.MODULATE_PUBLIC_ORIGIN || new URL(request.url).origin;
    if (
      request.headers.get('origin') !== allowed ||
      request.headers.get('sec-fetch-site') === 'cross-site'
    )
      return json({ error: 'Open the demo on its own website.' }, 403);
    const token =
      request.headers
        .get('cookie')
        ?.split(';')
        .map((s) => s.trim())
        .find((s) => s.startsWith(cookieName + '='))
        ?.slice(cookieName.length + 1) || '';
    const [sid, exp, sig] = token.split('.');
    if (
      !/^[a-f0-9-]{36}$/.test(sid) ||
      Number(exp) <= now ||
      Number(exp) > now + 28800 ||
      !equal(sig, hmac(`${sid}.${exp}`)) ||
      !equal(request.headers.get('x-demo-csrf'), hmac(`csrf:${token}`))
    )
      return json({ error: 'Your demo session expired. Reload and try again.' }, 403);
    if (!request.headers.get('content-type')?.startsWith('application/json'))
      return json({ error: 'JSON required' }, 415);
    let body;
    try {
      const reader = request.body.getReader();
      const parts = [];
      let length = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        length += value.byteLength;
        if (length > 70000) {
          await reader.cancel();
          return json({ error: 'Request too large' }, 413);
        }
        parts.push(value);
      }
      body = JSON.parse(Buffer.concat(parts).toString('utf8'));
      if (
        typeof body.prompt !== 'string' ||
        !body.prompt.trim() ||
        body.prompt.length > 1200 ||
        !Array.isArray(body.modules) ||
        !body.modules.includes('display') ||
        body.modules.length > 5 ||
        new Set(body.modules).size !== body.modules.length ||
        body.modules.some((m) => !MODULE_IDS.includes(m))
      )
        throw Error();
      if (body.previous) validatePackage(body.previous);
    } catch {
      return json(
        { error: 'Provide a request and attach a display with supported components.' },
        400,
      );
    }
    const id = randomUUID();
    try {
      await budget('start', {
        id,
        session: hmac(`session:${sid}`),
        network: hmac(
          `network:${request.headers.get('x-vercel-forwarded-for') || (env.NODE_ENV === 'development' ? request.headers.get('x-forwarded-for') : 'unknown') || 'local'}`,
        ),
      });
    } catch (e) {
      return json({ error: e.message }, 429);
    }
    const encoder = new TextEncoder();
    const disconnected = new AbortController();
    const stream = new ReadableStream({
      cancel() {
        disconnected.abort();
      },
      async start(controller) {
        const emit = (data) => {
          try {
            controller.enqueue(encoder.encode(JSON.stringify(data) + '\n'));
          } catch {}
        };
        try {
          const result = await generateApp({
            prompt: body.prompt.trim(),
            modules: body.modules,
            previous: body.previous,
            id,
            budget,
            emit,
            signal: AbortSignal.any([request.signal, disconnected.signal]),
            apiKey: env.MODULATE_META_API_KEY,
            fetchImpl,
          });
          emit({ type: 'result', ...result });
        } catch (error) {
          emit({
            type: 'error',
            error:
              error.name === 'AbortError'
                ? 'Generation cancelled.'
                : String(error.message).slice(0, 400),
          });
        } finally {
          try {
            await budget('finish', { id });
          } catch {}
          try {
            controller.close();
          } catch {}
        }
      },
    });
    return new Response(stream, {
      headers: {
        'Content-Type': 'application/x-ndjson',
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
      },
    });
  };
}
