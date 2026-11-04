const { test } = require('node:test');
const assert = require('node:assert/strict');
const app = {
  title: 'Test counter',
  description: 'A test fixture, never shipped as a demo app.',
  requires: ['display', 'buttons'],
  controls: { buttons: 'A increments' },
  code: 'function init(){return {n:0};} function update(s,i,dt){return {n:s.n+(i.button_a?1:0)}} function draw(s){return [{op:"clear",color:"#001122"},{op:"text",x:3,y:5,size:10,text:String(s.n),color:"#ffffff"}]}',
};
async function setup() {
  return {
    ...(await import('../shared/demo-runtime.mjs')),
    Q: await require('quickjs-emscripten').getQuickJS(),
  };
}
test('generated logic responds to input inside QuickJS', async () => {
  const { Q, createMachine, verifyPackage } = await setup();
  const m = createMachine(Q, app, app.requires);
  try {
    assert.equal(m.frame()[1].text, '0');
    assert.equal(m.frame({ button_a: true })[1].text, '1');
  } finally {
    m.close();
  }
  assert.equal(verifyPackage(Q, app, app.requires).frames, 151);
});
test('rejects unavailable capabilities, invalid frames and oversized state', async () => {
  const { Q, verifyPackage } = await setup();
  assert.throws(() => verifyPackage(Q, app, ['display']), /Attach buttons/);
  for (const code of [
    'function init(){return {}}function update(s){return s}function draw(){return [{op:"html",text:"<script>"}]}',
    'function init(){return "x".repeat(33000)}function update(s){return s}function draw(){return []}',
  ])
    assert.throws(() => verifyPackage(Q, { ...app, code }, app.requires));
});
test('infinite loops are interrupted; generated code has no network, DOM or process access', async () => {
  const { Q, verifyPackage } = await setup();
  const start = Date.now();
  assert.throws(
    () => verifyPackage(Q, { ...app, code: 'while(true){} /* infinite loop */' }, app.requires),
    /interrupt/,
  );
  assert.ok(Date.now() - start < 1500);
  const code =
    'function init(){if(typeof fetch!=="undefined"||typeof document!=="undefined"||typeof process!=="undefined"||typeof require!=="undefined")throw Error("host leak");return {}} function update(s){return s}function draw(){return [{op:"clear",color:"#000000"}]}';
  assert.equal(verifyPackage(Q, { ...app, code }, app.requires).passed, true);
});
const reply = (content, n) =>
  Response.json({
    id: 'meta-' + n,
    usage: { prompt_tokens: 100, completion_tokens: 80 },
    choices: [{ message: { content: JSON.stringify(content) } }],
  });
async function agent(replies, extra = {}) {
  const { runAgent } = await import('../server/demo-generation.mjs');
  const calls = [],
    events = [],
    ledger = [];
  const result = await runAgent({
    prompt: 'test request',
    modules: [...app.requires, 'computer', 'encoder'],
    id: 'test',
    apiKey: 'test',
    budget: async (a, b) => {
      ledger.push([a, b]);
      return {};
    },
    emit: (e) => events.push(e),
    fetchImpl: async (url, options) => {
      calls.push(JSON.parse(options.body));
      return reply(replies[calls.length - 1], calls.length);
    },
    ...extra,
  });
  return { result, calls, events, ledger };
}
const plan = (action, rest = {}) => ({ action, skill: 'games', say: 'On it.', why: 'test', ...rest });
test('orchestrator, coder and reviewer each get one bounded call; reviewer sees real checks', async () => {
  const { result, calls, events, ledger } = await agent([
    plan('build', { brief: 'counter on A' }),
    app,
    { approved: true, reason: 'Counter increments on A' },
  ]);
  assert.equal(calls.length, 3);
  assert.match(calls[0].messages[0].content, /orchestrator/);
  assert.match(calls[1].messages[0].content, /coder subagent/);
  assert.match(calls[2].messages.at(-1).content, /"frames":151/);
  assert.equal(result.kind, 'app');
  assert.equal(result.app.code, app.code);
  assert.deepEqual(
    result.inference.calls.map((c) => c.role),
    ['orchestrator', 'coder', 'reviewer'],
  );
  assert.deepEqual(
    result.trace.map((t) => t.role),
    ['orchestrator', 'coder', 'verifier', 'reviewer'],
  );
  assert.ok(events.some((e) => e.type === 'trace'));
  assert.equal(ledger.filter(([a]) => a === 'reserve').length, 3);
});
test('a failed check goes to the reviewer, whose repair must pass the same checks', async () => {
  const broken = { ...app, code: 'while(true){} /* infinite loop */' };
  const { result, calls } = await agent([plan('build'), broken, app]);
  assert.match(calls[2].messages.at(-1).content, /"passed":false/);
  assert.equal(result.app.code, app.code);
  assert.match(result.review, /repaired/);
  await assert.rejects(agent([plan('build'), broken, broken]), /still failed/);
  await assert.rejects(agent([plan('build'), broken, { approved: true }]), /not approved/);
});
test('bindings, refusals, questions and library actions need no generated code', async () => {
  const bound = await agent([
    plan('bind', {
      skill: 'hardware-controls',
      title: 'Knob brightness',
      bindings: [{ control: 'encoder', target: 'computer.brightness', step: -2 }],
    }),
  ]);
  assert.equal(bound.calls.length, 1);
  assert.equal(bound.result.kind, 'controls');
  assert.deepEqual(bound.result.app.requires, ['display', 'computer', 'encoder']);
  assert.equal(bound.result.app.bindings[0].step, -2);
  await assert.rejects(
    agent([plan('bind', { bindings: [{ control: 'encoder', target: 'os.shell', step: 2 }] })]),
    /Invalid control binding/,
  );
  const declined = await agent([plan('decline', { say: 'I can not clone badges.' })]);
  assert.equal(declined.result.kind, 'decline');
  assert.equal(declined.calls.length, 1);
  const asked = await agent([plan('ask', { question: 'Which game?' })]);
  assert.equal(asked.result.question, 'Which game?');
  const id = 'c'.repeat(64);
  const library = { open: true, entries: [{ id, title: 'Rust corridor', favorite: false }] };
  const fav = await agent([plan('library', { op: 'favorite', entry: 'cccccccc' })], { library });
  assert.deepEqual(fav.result.library, { op: 'favorite', entry: id, control: null });
  assert.match(fav.calls[0].messages[1].content, /"ref":"cccccccc"/);
  await assert.rejects(
    agent([plan('library', { op: 'trash', entry: 'deadbeef' })], { library }),
    /could not match/,
  );
});
test('the trusted bench, not the model, decides whether a driver install is allowed', async () => {
  const healthy = await agent([plan('debug', { op: 'install_driver', driver: 'lsm6ds3trc' })], {
    hardware: { imu: { attached: true, driver: 'ready' }, conflict: false },
  });
  assert.deepEqual(healthy.result.debug, { op: 'inspect', driver: null });
  const missing = await agent([plan('debug', { op: 'install_driver', driver: 'lsm6ds3trc' })], {
    hardware: { imu: { attached: true, driver: 'missing' }, conflict: false },
  });
  assert.deepEqual(missing.result.debug, { op: 'install_driver', driver: 'lsm6ds3trc' });
  const unknown = await agent([plan('debug', { op: 'install_driver', driver: 'rfid_cloner' })], {
    hardware: { imu: { attached: true, driver: 'missing' }, conflict: false },
  });
  assert.equal(unknown.result.debug.op, 'inspect');
});
test('missing usage or an unreadable plan cannot activate anything', async () => {
  const { runAgent } = await import('../server/demo-generation.mjs');
  let settled = false;
  await assert.rejects(
    runAgent({
      prompt: 'x',
      modules: app.requires,
      id: 'x',
      apiKey: 'x',
      budget: async (a) => {
        if (a === 'settle') settled = true;
        return {};
      },
      emit: () => {},
      fetchImpl: async () =>
        Response.json({ choices: [{ message: { content: JSON.stringify(plan('build')) } }] }),
    }),
    /usage was missing/,
  );
  assert.equal(settled, false);
  await assert.rejects(agent(['not json at all']), /unreadable plan/);
});
test('camera, tilt and control-mapping contracts are enforced by the shared verifier', async () => {
  const { Q, verifyPackage, validateFrame, applyBinding } = await setup();
  const tilt = {
    ...app,
    requires: ['display', 'imu'],
    controls: { imu: 'Tilt to move' },
    code: 'function init(){return {x:0}} function update(s,i){return {x:i.tilt.x}} function draw(s){return [{op:"clear",color:"#000000"},{op:"text",x:1,y:1,size:8,text:String(s.x),color:"#ffffff"}]}',
  };
  assert.equal(verifyPackage(Q, tilt, tilt.requires).passed, true);
  const cam = { op: 'camera', x: 0, y: 0, w: 240, h: 135, mirror: true, pixelate: 2, palette: 'neon' };
  const clear = { op: 'clear', color: '#000000' };
  assert.doesNotThrow(() => validateFrame([clear, cam], ['display', 'camera']));
  assert.throws(() => validateFrame([clear, cam], ['display']), /camera/);
  assert.throws(() => validateFrame([clear, cam, cam], ['display', 'camera']), /camera/);
  assert.throws(() => validateFrame([clear, { ...cam, palette: 'raw' }], ['display', 'camera']));
  const controls = {
    kind: 'controls',
    title: 'Knob',
    description: '',
    requires: ['display', 'computer', 'encoder'],
    controls: { encoder: 'Knob: brightness +2' },
    bindings: [{ control: 'encoder', target: 'computer.brightness', step: 2 }],
  };
  assert.equal(verifyPackage(Q, controls, controls.requires).passed, true);
  assert.throws(() => verifyPackage(Q, controls, ['display', 'encoder']), /Attach computer/);
  for (const bad of [
    { ...controls, bindings: [{ control: 'encoder', target: 'computer.brightness', step: 0 }] },
    { ...controls, bindings: [{ control: 'encoder', target: 'computer.fans', step: 1 }] },
    { ...controls, code: 'function init(){}' },
  ])
    assert.throws(() => verifyPackage(Q, bad, controls.requires));
  assert.deepEqual(applyBinding({ brightness: 99, volume: 5 }, controls.bindings[0], 3), {
    brightness: 100,
    volume: 5,
  });
});
test('API blocks cross-origin, forged sessions and invalid bodies before inference', async () => {
  const { demoHandler } = await import('../server/demo-api.mjs');
  let calls = 0;
  const handler = demoHandler(
    {
      MODULATE_META_API_KEY: 'test',
      MODULATE_REMOTE_SECRET: 's'.repeat(40),
      MODULATE_PUBLIC_ORIGIN: 'https://demo.test',
    },
    async () => {
      calls++;
      throw Error('unexpected');
    },
  );
  const res = await handler(new Request('https://demo.test/api/demo'));
  const token = res.headers.get('set-cookie').split(';')[0],
    csrf = (await res.json()).csrf;
  for (const origin of ['https://evil.test', 'null'])
    assert.equal(
      (
        await handler(
          new Request('https://demo.test/api/demo', {
            method: 'POST',
            headers: {
              origin,
              cookie: token,
              'x-demo-csrf': csrf,
              'content-type': 'application/json',
            },
            body: '{}',
          }),
        )
      ).status,
      403,
    );
  assert.equal(
    (
      await handler(
        new Request('https://demo.test/api/demo', {
          method: 'POST',
          headers: {
            origin: 'https://demo.test',
            cookie: token,
            'x-demo-csrf': csrf,
            'content-type': 'application/json',
          },
          body: JSON.stringify({ prompt: 'x', modules: ['shell'] }),
        }),
      )
    ).status,
    400,
  );
  assert.equal(calls, 0);
});
test('syntax and runtime failures name the generated line for the repair loop', async () => {
  const { Q, verifyPackage } = await setup();
  const code =
    'function init(){return {n:0}}\nfunction update(s){return {n:(s.n+1}}\nfunction draw(s){return [{op:"clear",color:"#000000"}]}';
  assert.throws(() => verifyPackage(Q, { ...app, code }, app.requires), /line 2.*update/);
  const crash =
    'function init(){return {}}\nfunction update(s){return s}\nfunction draw(s){return s.missing.value}';
  assert.throws(() => verifyPackage(Q, { ...app, code: crash }, app.requires), /line 3/);
});
