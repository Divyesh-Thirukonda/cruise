const { test } = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
async function setup() {
  const { DemoBudget, CALL_HOLD } = await import(
    '../../../deploy/discovery-worker/demo-budget.mjs'
  );
  let state;
  let queue = Promise.resolve();
  const storage = {
    get: async () => (state ? structuredClone(state) : undefined),
    put: async (k, v) => {
      state = structuredClone(v);
    },
    transaction: (fn) => {
      const p = queue.then(() => fn(storage));
      queue = p.catch(() => {});
      return p;
    },
  };
  const obj = new DemoBudget({ storage });
  const call = async (action, body = {}) => {
    const r = await obj.fetch(
      new Request('https://budget/' + action, { method: 'POST', body: JSON.stringify(body) }),
    );
    return { status: r.status, ...(await r.json()) };
  };
  return { call, CALL_HOLD };
}
test('allocation is fixed, concurrent reservations cannot exceed its cap, unknown costs stay held', async () => {
  const { call, CALL_HOLD } = await setup();
  assert.equal(
    (await call('start', { id: randomUUID(), session: 'a'.repeat(64), network: 'b'.repeat(64) }))
      .status,
    429,
  );
  await call('allocate', { reservation: 'c'.repeat(32), amount: 2000000 });
  assert.equal(
    (await call('allocate', { reservation: 'd'.repeat(32), amount: 8000000 })).status,
    409,
  );
  const ids = [randomUUID(), randomUUID()];
  for (let i = 0; i < 2; i++)
    await call('start', {
      id: ids[i],
      session: String(i).repeat(64),
      network: String(i + 2).repeat(64),
    });
  const rs = await Promise.all(ids.map((id) => call('reserve', { id, call: 0 })));
  assert.deepEqual(rs.map((r) => r.status).sort(), [200, 429]);
  await call('finish', { id: ids[0] });
  assert.equal((await call('status')).charged, CALL_HOLD);
});
test('duplicate calls cannot infer twice; settlements are idempotent, overages halt', async () => {
  const { call, CALL_HOLD } = await setup();
  await call('allocate', { reservation: 'c'.repeat(32), amount: 5000000 });
  const id = randomUUID();
  await call('start', { id, session: 'a'.repeat(64), network: 'b'.repeat(64) });
  assert.equal(
    (await call('start', { id, session: 'a'.repeat(64), network: 'b'.repeat(64) })).status,
    409,
  );
  await call('reserve', { id, call: 0 });
  assert.equal((await call('reserve', { id, call: 0 })).status, 409);
  await call('settle', { id, call: 0, cost: 20000 });
  await call('settle', { id, call: 0, cost: 20000 });
  assert.equal((await call('status')).charged, 20000);
  await call('reserve', { id, call: 1 });
  await call('settle', { id, call: 1, cost: CALL_HOLD + 1 });
  assert.equal((await call('reserve', { id, call: 2 })).status, 409);
});
