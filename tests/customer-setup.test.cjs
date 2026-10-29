// Synthetic customer setup DOM tests; no live pairing, code, device or browser session.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('../webapp/connect-app-code/node_modules/jsdom');
const html = fs.readFileSync(path.join(__dirname, '../modulate/web/setup.html'), 'utf8').replaceAll('__CONNECT_URL__', 'https://modulate-connect.vercel.app/connect');
const script = fs.readFileSync(path.join(__dirname, '../modulate/web/setup.js'), 'utf8');
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(setImmediate); };
const future = () => Date.now() / 1000 + 180;
const native = () => ({code: '12345678', expires_at: future()});
const remote = () => ({code: '87654321', expires_at: future(), browser_count: 0});

async function setup(t, initial = {}, initialPairing = null) {
  const dom = new JSDOM(html, {url: 'http://127.0.0.1:8787/setup', runScripts: 'outside-only'});
  t.after(() => dom.window.close());
  const {window} = dom;
  const timers = [], ticks = [], requests = [];
  let snapshot = {device_connected: true, paired_mac: false, pairing_saved: false, local_ready: false,
    remote_enabled: false, browser_count: 0, pairing_expires_at: null, native_permissions: {}, browser_pairing: null,
    website_url: 'https://untrusted.example/not-used', ...initial};
  let pairing = initialPairing, offline = false, token = 'csrf-first', nextRead = null;
  let clipboardFails = false;
  const copied = [];
  Object.defineProperty(window.navigator, 'clipboard', {value: {writeText: async (text) => { if (clipboardFails) throw Error('Clipboard unavailable'); copied.push(text); }}});
  window.setInterval = (callback) => { ticks.push(callback); return ticks.length; };
  window.setTimeout = (callback, milliseconds) => { timers.push({callback, milliseconds}); return timers.length; };
  window.clearTimeout = () => {};
  window.fetch = async (url, options = {}) => {
    requests.push({url, options});
    if (offline) throw Error('Synthetic companion offline');
    if (url === '/api/csrf') return {ok:true,status:200,json:async()=>({token})};
    if (options.headers?.['X-CSRF-Token'] !== token) return {ok:false,status:403,json:async()=>({error:'Forbidden'})};
    let body;
    if (url === '/api/setup') {
      if(nextRead){const pending=nextRead;nextRead=null;return pending;}
      body = snapshot;
    } else if (url === '/api/pairing') body = {pending: pairing};
    else if (url === '/api/setup/pairing') { pairing = pairing || native(); body={pending:pairing,already_paired:false}; }
    else if (url === '/api/setup/browser-code') {snapshot.browser_pairing = snapshot.browser_pairing || remote(); body=snapshot;}
    else throw Error(`Unexpected route ${url}`);
    return {ok:true,status:200,json:async()=>structuredClone(body)};
  };
  window.eval(script); await settle();
  return {window, requests, copied, element:(id)=>window.document.getElementById(id),
    setState(value){snapshot={...snapshot,...value};}, setPairing(value){pairing=value;},
    rotateSession(){token='csrf-rotated';}, setOffline(value){offline=value;}, failClipboard(){clipboardFails=true;},
    holdNextRead(promise){nextRead=promise;}, tick(){for(const callback of ticks)callback();},
    async poll(){const index=timers.findIndex(t=>t.milliseconds===1000);assert.notEqual(index,-1);await timers.splice(index,1)[0].callback();await settle();},
    async click(id){this.element(id).click();await settle();}
  };
}
const pairedState = (more={}) => ({paired_mac:true,pairing_saved:true,local_ready:true,pairing_expires_at:future(),...more});
const posts = (ui, path) => ui.requests.filter(r=>r.options.method==='POST'&&(!path||r.url===path));

test('no grant starts merely by opening setup; device pending code is reused', async t=>{
  const ui=await setup(t);
  assert.equal(ui.element('pair').hidden,false); assert.equal(posts(ui).length,0);
  assert.equal(ui.element('retry').hidden,true);
  ui.setPairing(native()); await ui.click('pair');
  assert.equal(posts(ui).length,0,'fresh preflight sees a code started on the gadget');
  assert.equal(ui.element('comparison-code').textContent,'12345678');
  assert.equal(ui.element('comparison').hidden,false); assert.equal(ui.element('pair').hidden,true);
  assert.equal(ui.element('retry').hidden,true);
});

test('a deliberate click creates one comparison; expired code becomes non-actionable',async t=>{
  const ui=await setup(t);
  ui.element('pair').click();ui.element('pair').click();await settle();
  assert.equal(posts(ui,'/api/setup/pairing').length,1);
  assert.equal(ui.element('comparison-code').textContent,'12345678');
  ui.setPairing({code:'12345678',expires_at:Date.now()/1000-1});await ui.poll();
  assert.equal(ui.element('comparison-code').textContent,'');assert.equal(ui.element('comparison').hidden,true);
  assert.equal(ui.element('pair').hidden,false);assert.equal(posts(ui).length,1);
});

test('pairing saved while gadget offline does not claim active access or show any code',async t=>{
  const ui=await setup(t,pairedState({device_connected:false,local_ready:false,remote_enabled:true}));
  assert.match(ui.element('title').textContent,/access is saved/);
  assert.equal(ui.element('prepare-website').hidden,true);assert.equal(ui.element('comparison').hidden,true);
  assert.equal(ui.element('website-link').hidden,true);assert.equal(posts(ui).length,0);
  assert.equal(ui.element('retry').hidden,false);
});

test('gateway setup remains an agent step; restarting companion renews the local session',async t=>{
  const ui=await setup(t,pairedState());
  assert.match(ui.element('title').textContent,/One more connection step/);assert.equal(ui.element('prepare-website').hidden,true);
  assert.equal(ui.element('retry').hidden,false);
  ui.rotateSession();ui.setState({remote_enabled:true});await ui.poll();
  assert.equal(ui.requests.filter(r=>r.url==='/api/csrf').length,2);
  assert.equal(ui.element('prepare-website').hidden,false);assert.equal(posts(ui).length,0);
  assert.equal(ui.element('retry').hidden,true);
});

test('browser code is explicit and stable during polls; completion needs a new browser session',async t=>{
  const ui=await setup(t,pairedState({remote_enabled:true}));
  assert.equal(ui.element('website-code-panel').hidden,true);assert.equal(posts(ui).length,0);
  assert.equal(ui.element('title').textContent,'Finish connecting.');
  assert.equal(ui.element('retry').hidden,true);
  ui.element('prepare-website').click();ui.element('prepare-website').click();await settle();
  assert.equal(posts(ui,'/api/setup/browser-code').length,1);
  assert.equal(ui.element('website-code').textContent,'87654321');
  assert.equal(ui.element('retry').hidden,true);
  await ui.poll();assert.equal(posts(ui).length,1);
  ui.setState({browser_pairing:null,browser_count:1});await ui.poll();
  assert.equal(ui.element('website-code').textContent,'');assert.equal(ui.element('website-link').hidden,false);
  assert.equal(ui.element('website-link').href,'https://modulate-connect.vercel.app/connect');
  assert.equal(ui.element('title').textContent,'Continue on Modulate');
  assert.equal(ui.element('description').textContent,'A browser connection was added. The website will check this browser’s session.');
  assert.equal(ui.element('retry').hidden,true);
  ui.setState({browser_count:0});await ui.poll();
  assert.equal(ui.element('website-link').hidden,true);assert.equal(ui.element('prepare-website').hidden,false);
});

test('an invalidated offer cannot be completed by a later unrelated browser',async t=>{
  const ui=await setup(t,pairedState({remote_enabled:true,browser_pairing:remote()}));
  ui.setState({browser_pairing:null,browser_count:0});await ui.poll();
  assert.equal(ui.element('website-link').hidden,true);
  ui.setState({browser_pairing:null,browser_count:1});await ui.poll();
  assert.equal(ui.element('website-link').hidden,true);
  assert.equal(ui.element('prepare-website').hidden,false);
  assert.equal(ui.element('title').textContent,'Finish connecting.');
});

test('expired website code is cleared without claiming a successful connection',async t=>{
  const ui=await setup(t,pairedState({remote_enabled:true,browser_pairing:{...remote(),expires_at:Date.now()/1000-1}}));
  assert.equal(ui.element('website-code').textContent,'');assert.equal(ui.element('website-link').hidden,true);
  assert.equal(ui.element('prepare-website').hidden,false);assert.equal(posts(ui).length,0);
});

test('clipboard failure keeps a manual website link across render ticks',async t=>{
  const ui=await setup(t,pairedState({remote_enabled:true,browser_pairing:remote()}));
  ui.failClipboard();await ui.click('continue-website');ui.tick();
  assert.equal(ui.element('website-link').hidden,false);
  assert.match(ui.element('notice').textContent,/Copy the code shown above/);
  assert.equal(ui.element('website-link').href,'https://modulate-connect.vercel.app/connect');
});

test('malformed current status fails closed and never mints a code',async t=>{
  const ui=await setup(t,pairedState({remote_enabled:true}));
  ui.setState({pairing_expires_at:null});await ui.click('prepare-website');
  assert.equal(posts(ui).length,0);assert.equal(ui.element('prepare-website').hidden,true);
  assert.equal(ui.element('website-code').textContent,'');assert.equal(ui.element('website-link').hidden,true);
  assert.equal(ui.element('retry').hidden,false);
});

test('denied native permissions are explained without blocking unrelated connection features',async t=>{
  const ui=await setup(t,pairedState({remote_enabled:true,native_permissions:{screen_recording:false,accessibility:true}}));
  assert.equal(ui.element('permission-note').hidden,false);assert.match(ui.element('permission-note').textContent,/Screen Recording/);
  assert.equal(ui.element('prepare-website').hidden,false);
});

test('late stale poll cannot replace a newer paired status or re-open its comparison',async t=>{
  const ui=await setup(t);
  let release;ui.holdNextRead(new Promise(resolve=>{release=resolve;}));
  const oldPoll=ui.poll();await settle();
  ui.setState(pairedState({remote_enabled:false}));await ui.click('pair');
  assert.match(ui.element('title').textContent,/One more connection step/);
  release({ok:true,status:200,json:async()=>({device_connected:true,paired_mac:false,pairing_saved:false,local_ready:false,remote_enabled:false,browser_count:0,pairing_expires_at:null,native_permissions:{},browser_pairing:null})});
  await oldPoll;assert.match(ui.element('title').textContent,/One more connection step/);
  assert.equal(ui.element('comparison').hidden,true);assert.equal(posts(ui).length,0);
});
