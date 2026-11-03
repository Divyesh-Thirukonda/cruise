// A separately allocated slice of the existing $50 ledger. No prompts, code, keys or raw IPs.
export const CALL_HOLD = 1345536; // microdollars: full 1,048,576-token context + 8,192 output.
const json = (body, status = 200) =>
  Response.json(body, { status, headers: { 'Cache-Control': 'no-store' } });
export class DemoBudget {
  constructor(ctx) {
    this.ctx = ctx;
  }
  async fetch(request) {
    const action = new URL(request.url).pathname.split('/').pop();
    if (request.method !== 'POST') return json({ error: 'Method not allowed' }, 405);
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: 'Invalid JSON' }, 400);
    }
    return this.ctx.storage.transaction(async (storage) => {
      const ledger = (await storage.get('ledger')) || {
        allocation: null,
        limit: 0,
        charged: 0,
        halted: false,
        requests: {},
        rates: {},
      };
      const result = (value, status = 200) => json(value, status);
      if (action === 'status')
        return result({
          limit: ledger.limit,
          charged: ledger.charged,
          halted: ledger.halted,
          allocation: ledger.allocation,
        });
      if (action === 'allocate') {
        if (
          !/^[a-f0-9]{32}$/.test(body.reservation || '') ||
          !Number.isSafeInteger(body.amount) ||
          body.amount < 1 ||
          body.amount > 8000000
        )
          return result({ error: 'Invalid allocation' }, 400);
        if (
          ledger.allocation &&
          (ledger.allocation !== body.reservation || ledger.limit !== body.amount)
        )
          return result({ error: 'Allocation already fixed' }, 409);
        ledger.allocation = body.reservation;
        ledger.limit = body.amount;
      } else if (action === 'start') {
        if (
          !/^[a-f0-9-]{36}$/.test(body.id || '') ||
          !['session', 'network'].every((k) => /^[a-f0-9]{64}$/.test(body[k] || ''))
        )
          return result({ error: 'Invalid request' }, 400);
        if (ledger.requests[body.id]) return result({ error: 'Request already started' }, 409);
        if (ledger.halted || ledger.limit - ledger.charged < CALL_HOLD)
          return result(
            { error: 'The shared demo allowance is unavailable. Saved apps still work.' },
            429,
          );
        if (Object.keys(ledger.requests).length >= 2000)
          return result({ error: 'Demo allowance needs review' }, 429);
        const now = Date.now(),
          day = Math.floor(now / 86400000);
        for (const [key, value] of Object.entries(ledger.rates))
          if (value.day !== day) delete ledger.rates[key];
        for (const key of [body.session, body.network]) {
          const rate = ledger.rates[key] || { day, count: 0, last: 0 };
          if (rate.count >= (key === body.session ? 6 : 24) || now - rate.last < 10000)
            return result(
              {
                error:
                  'Please wait before generating again. Each visitor has a small daily allowance.',
              },
              429,
            );
        }
        if (
          Object.values(ledger.requests).some(
            (r) => r.session === body.session && !r.finished && now - r.at < 300000,
          )
        )
          return result({ error: 'A generation is already running in this browser.' }, 409);
        for (const key of [body.session, body.network]) {
          const r = ledger.rates[key] || { day, count: 0 };
          ledger.rates[key] = { ...r, count: r.count + 1, last: now };
        }
        ledger.requests[body.id] = { session: body.session, at: now, calls: {}, finished: false };
      } else {
        const job = ledger.requests[body.id];
        if (!job) return result({ error: 'Unknown request' }, 404);
        if (action === 'reserve') {
          if (
            job.finished ||
            ledger.halted ||
            !Number.isInteger(body.call) ||
            body.call < 0 ||
            body.call > 2
          )
            return result({ error: 'Call not allowed' }, 409);
          if (job.calls[body.call])
            return result({ error: 'Call already reserved; do not retry inference' }, 409);
          if (ledger.charged + CALL_HOLD > ledger.limit)
            return result({ error: 'The shared demo allowance is currently exhausted.' }, 429);
          ledger.charged += CALL_HOLD;
          job.calls[body.call] = { held: CALL_HOLD };
        } else if (action === 'settle') {
          const call = job.calls[body.call];
          if (!call || !Number.isSafeInteger(body.cost) || body.cost < 0)
            return result({ error: 'Invalid settlement' }, 400);
          if (call.cost !== undefined) {
            if (call.cost !== body.cost) return result({ error: 'Settlement conflict' }, 409);
          } else {
            ledger.charged += body.cost - call.held;
            call.cost = body.cost;
            if (body.cost > call.held) ledger.halted = true;
          }
        } else if (action === 'finish') job.finished = true;
        else return result({ error: 'Unknown operation' }, 404);
      }
      await storage.put('ledger', ledger);
      return result({ ok: true, remaining: ledger.limit - ledger.charged, halted: ledger.halted });
    });
  }
}
