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
test('Meta receives actual check results and must approve before activation', async () => {
  const { generateApp } = await import('../server/demo-generation.mjs');
  const calls = [],
    events = [],
    ledger = [];
  const result = await generateApp({
    prompt: 'counter',
    modules: app.requires,
    id: 'test',
    apiKey: 'test',
    budget: async (a, b) => {
      ledger.push([a, b]);
      return {};
    },
    emit: (e) => events.push(e),
    fetchImpl: async (url, options) => {
      calls.push(JSON.parse(options.body));
      return Response.json({
        id: 'meta-' + calls.length,
        usage: { prompt_tokens: 100, completion_tokens: 80 },
        choices: [
          {
            message: {
              content: JSON.stringify(
                calls.length === 1
                  ? app
                  : { approved: true, reason: 'Input counter matches request' },
              ),
            },
          },
        ],
      });
    },
  });
  assert.equal(calls.length, 2);
  assert.match(calls[1].messages.at(-1).content, /"frames":151/);
  assert.equal(result.app.code, app.code);
  assert.equal(result.inference.calls[0].responseId, 'meta-1');
  assert.equal(ledger.filter(([a]) => a === 'reserve').length, 2);
});
test('failed checks trigger bounded repair; no approval or malformed usage cannot activate', async () => {
  const { generateApp } = await import('../server/demo-generation.mjs');
  const messages = [];
  await assert.rejects(
    generateApp({
      prompt: 'test',
      modules: app.requires,
      id: 'x',
      apiKey: 'test',
      budget: async () => ({}),
      emit: () => {},
      fetchImpl: async (u, o) => {
        messages.push(JSON.parse(o.body));
        return Response.json({
          usage: { prompt_tokens: 1, completion_tokens: 1 },
          choices: [
            {
              message: {
                content: JSON.stringify({ ...app, code: 'while(true){} /* infinite loop */' }),
              },
            },
          ],
        });
      },
    }),
    /three calls/,
  );
  assert.equal(messages.length, 3);
  assert.match(messages[1].messages.at(-1).content, /"passed":false/);
  let settled = false;
  await assert.rejects(
    generateApp({
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
        Response.json({ choices: [{ message: { content: JSON.stringify(app) } }] }),
    }),
    /usage was missing/,
  );
  assert.equal(settled, false);
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
