// Synthetic local Studio DOM tests; no live pairing, Mac access, or network.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('../webapp/connect-app-code/node_modules/jsdom');
const html = fs.readFileSync(path.join(__dirname, '../modulate/web/index.html'), 'utf8');
const script = fs.readFileSync(path.join(__dirname, '../modulate/web/app.js'), 'utf8');
const pending = () => ({code: '12345678', expires_at: Date.now() / 1000 + 120, host_url: 'https://192.0.2.8:8788'});
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(setImmediate); };

async function studio(t, initial = {}) {
  const dom = new JSDOM(html, {url: 'http://127.0.0.1:8787/', runScripts: 'outside-only'});
  t.after(() => dom.window.close());
  const {window} = dom;
  const timers = [];
  const requests = [];
  let snapshot = {paired: false, device: {connected: true}, remote: {enabled: false}, ...initial};
  let pairing = null;
  let offline = false;
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new window.Event('close')); };
  window.setInterval = () => 0;
  window.setTimeout = (callback, milliseconds) => { timers.push({callback, milliseconds}); return timers.length; };
  window.clearTimeout = () => {};
  window.fetch = async (url, options = {}) => {
    requests.push({url, options});
    if (offline) throw new Error('Synthetic offline');
    let body;
    if (url === '/api/csrf') body = {token: 'synthetic-csrf'};
    else if (url === '/api/state') body = snapshot;
    else if (url === '/api/pairing' && options.method === 'POST') body = pairing = pending();
    else if (url === '/api/pairing') body = {pending: pairing};
    else throw new Error(`Unexpected synthetic request ${url}`);
    return {ok: true, status: 200, json: async () => structuredClone(body)};
  };
  window.eval(script);
  await settle();
  return {window, requests, element: (id) => window.document.getElementById(id),
    setPairing: (value) => { pairing = value; }, setState: (value) => { snapshot = {...snapshot, ...value}; },
    setOffline: (value) => { offline = value; },
    async poll() {
      const at = timers.findIndex((entry) => entry.milliseconds === 750);
      assert.notEqual(at, -1, 'next polling task exists');
      const task = timers.splice(at, 1)[0];
      await task.callback();
      await settle();
    }};
}

test('device-initiated pending code appears without minting or rotating it', async (t) => {
  const ui = await studio(t);
  const request = pending();
  ui.setPairing(request);
  await ui.poll();
  assert.equal(ui.element('pairing-dialog').open, true);
  assert.equal(ui.element('pairing-code').textContent, request.code);
  assert.equal(ui.element('pairing-host-url').textContent, request.host_url);
  assert.equal(ui.requests.filter((r) => r.options.method === 'POST').length, 0);
  assert.ok(ui.requests.filter((r) => r.url === '/api/pairing').every((r) => r.options.headers['X-CSRF-Token'] === 'synthetic-csrf'));
  ui.element('pairing-dialog').close();
  await ui.poll();
  assert.equal(ui.element('pairing-dialog').open, false, 'polling does not keep reopening a dismissed comparison');
  ui.element('pairing-open').click();
  await settle();
  assert.equal(ui.element('pairing-dialog').open, true);
  assert.equal(ui.requests.filter((r) => r.options.method === 'POST').length, 0, 'View comparison reuses pending request');
});

test('expired or replaced request does not leave an actionable stale comparison', async (t) => {
  const ui = await studio(t);
  ui.setPairing(pending());
  await ui.poll();
  ui.setPairing(null);
  await ui.poll();
  assert.equal(ui.element('pairing-code').hidden, true);
  assert.equal(ui.element('pairing-code').textContent, '');
  assert.match(ui.element('pairing-expiry').textContent, /No active comparison/);
  const next = {...pending(), code: '87654321'};
  ui.setPairing(next);
  await ui.poll();
  assert.equal(ui.element('pairing-code').textContent, next.code);
});

test('saved pairing is not displayed as active while device or Studio is offline', async (t) => {
  const ui = await studio(t, {paired: true, device: {connected: false}, volume: {volume: 40, muted: false}});
  assert.equal(ui.element('paired-chip').textContent, 'PAIRING SAVED');
  assert.match(ui.element('pairing-status').textContent, /device offline/);
  assert.equal(ui.element('volume-display').hidden, true);
  ui.setState({device: {connected: true}});
  await ui.poll();
  assert.equal(ui.element('paired-chip').textContent, 'MAC LINK ACTIVE');
  assert.equal(ui.element('volume-display').hidden, false);
  ui.setOffline(true);
  await ui.poll();
  assert.equal(ui.element('paired-chip').textContent, 'PAIRING SAVED');
  assert.match(ui.element('pairing-status').textContent, /Studio offline/);
  assert.equal(ui.element('volume-display').hidden, true);
});

test('physical approval between POST and refresh never resurrects the comparison code', async (t) => {
  const ui = await studio(t);
  const originalFetch = ui.window.fetch;
  ui.window.fetch = async (url, options) => {
    const response = await originalFetch(url, options);
    if (url === '/api/pairing' && options?.method === 'POST') {
      ui.setPairing(null);
      ui.setState({paired: true});
    }
    return response;
  };
  ui.element('pairing-open').click();
  await settle();
  assert.equal(ui.element('pairing-code').hidden, true);
  assert.equal(ui.element('pairing-code').textContent, '');
  assert.match(ui.element('pairing-expiry').textContent, /Mac link active/);
});
