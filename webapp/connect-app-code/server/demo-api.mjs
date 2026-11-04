import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';
import { getQuickJS } from 'quickjs-emscripten';
import { runAgent, MODEL } from './demo-generation.mjs';
import { MODULE_IDS, validatePackage } from '../shared/demo-runtime.mjs';
const cookieName = 'modulate_demo';
const json = (data, status = 200, headers = {}) =>
  Response.json(data, { status, headers: { 'Cache-Control': 'private, no-store', ...headers } });
const equal = (a, b) =>
  typeof a === 'string' &&
  typeof b === 'string' &&
  Buffer.byteLength(a) === Buffer.byteLength(b) &&
  timingSafeEqual(Buffer.from(a), Buffer.from(b));
const short = (value, max) =>
  typeof value === 'string' ? value.replace(/[\u0000-\u001f]/g, ' ').slice(0, max) : '';
// Client state is untrusted data for the model; keep only the expected shape and sizes.
export function sanitizeLibrary(library) {
  if (!library || typeof library !== 'object') return { open: false, entries: [] };
  const entries = Array.isArray(library.entries) ? library.entries.slice(0, 24) : [];
  return {
    open: library.open === true,
    entries: entries
      .filter((e) => e && /^[a-f0-9]{64}$/.test(e.id))
      .map((e) => ({
        id: e.id,
        title: short(e.title, 80),
        kind: e.kind === 'controls' ? 'controls' : 'app',
        favorite: e.favorite === true,
        trashed: e.trashed === true,
      })),
  };
}
export function sanitizeComputer(computer) {
  const level = (v) => (Number.isInteger(v) && v >= 0 && v <= 100 ? v : null);
  if (!computer || typeof computer !== 'object') return null;
  return { brightness: level(computer.brightness), volume: level(computer.volume) };
}
export function sanitizeHardware(hardware) {
  if (!hardware || typeof hardware !== 'object') return null;
  const bus = Array.isArray(hardware.bus) ? hardware.bus.slice(0, 12) : [];
  return {
    bus: bus
      .filter((d) => d && /^0x[0-7][0-9a-f]$/.test(d.address))
      .map((d) => ({
        address: d.address,
        device: short(d.device, 60),
        status: short(d.status, 80),
      })),
    imu: {
      attached: hardware.imu?.attached === true,
      driver: ['ready', 'missing'].includes(hardware.imu?.driver) ? hardware.imu.driver : 'none',
    },
    conflict: hardware.conflict === true,
    repair: short(hardware.repair, 40) || null,
  };
}
export function sanitizeHistory(history) {
  if (!Array.isArray(history)) return [];
  return history
    .slice(-8)
    .filter((h) => h && ['user', 'assistant'].includes(h.role))
    .map((h) => ({ role: h.role, text: short(h.text, 300) }));
}
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
        body.modules.length > MODULE_IDS.length ||
        new Set(body.modules).size !== body.modules.length ||
        body.modules.some((m) => !MODULE_IDS.includes(m))
      )
        throw Error();
      if (body.previous) validatePackage(body.previous);
      body.channel = body.channel === 'muse' ? 'muse' : 'device';
      body.library = sanitizeLibrary(body.library);
      body.computer = sanitizeComputer(body.computer);
      body.hardware = sanitizeHardware(body.hardware);
      body.history = sanitizeHistory(body.history);
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
          const result = await runAgent({
            prompt: body.prompt.trim(),
            channel: body.channel,
            modules: body.modules,
            previous: body.previous,
            library: body.library,
            computer: body.computer,
            hardware: body.hardware,
            history: body.history,
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
