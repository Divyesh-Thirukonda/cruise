/* Narrow local connection flow. No model calls, generated content, or automatic grants. */
(() => {
  const $ = (id) => document.getElementById(id);
  const website = $('website-link').href; // Fixed server-rendered deployment URL, never response/user input.
  const ui = {csrf: '', state: null, pairing: null, online: false, busy: false, epoch: 0,
    lastRead: 0, seenWebsite: null, websiteLinked: false, clipboardFallback: false, error: '', errorPhase: ''};
  let pollTimer;
  const now = () => Date.now() / 1000;
  const validCode = (value) => value && typeof value.code === 'string' && /^\d{8}$/.test(value.code) &&
    Number.isFinite(value.expires_at) && value.expires_at > now();
  const remaining = (expiry) => { const seconds = Math.max(0, Math.ceil(expiry - now())); return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`; };

  async function renewSession() {
    const response = await fetch('/api/csrf', {cache: 'no-store'});
    const data = await response.json();
    if (!response.ok || typeof data.token !== 'string' || !data.token || data.token.length > 256) throw Error('The Mac connection session is unavailable.');
    ui.csrf = data.token;
  }
  async function api(path, body, retry = true) {
    const options = {headers: {'X-CSRF-Token': ui.csrf}, cache: 'no-store'};
    if (body !== undefined) { options.method = 'POST'; options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
    const response = await fetch(path, options);
    if (response.status === 403 && retry) {
      // A companion restart rotates its local session. A 403 did not dispatch
      // this request, so renew and retry once, never repeatedly mint or mutate.
      await renewSession(); return api(path, body, false);
    }
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'The connection step could not finish. Check the current gadget screen and try again.');
    return data;
  }
  function validateSnapshot(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value) ||
        ['device_connected','paired_mac','local_ready','remote_enabled'].some((key) => typeof value[key] !== 'boolean') ||
        !Number.isInteger(value.browser_count) || value.browser_count < 0 ||
        (value.paired_mac && (!Number.isFinite(value.pairing_expires_at) || value.pairing_expires_at <= 0)) ||
        (value.local_ready && (!value.paired_mac || !value.device_connected)) ||
        !value.native_permissions || typeof value.native_permissions !== 'object' || Array.isArray(value.native_permissions) ||
        ['screen_recording','accessibility'].some((key) => ![true,false,null,undefined].includes(value.native_permissions[key])) ||
        (value.browser_pairing !== null && !codeShape(value.browser_pairing))) {
      throw Error('The companion returned an incomplete connection status. Ask your agent to check it.');
    }
    return value;
  }
  function codeShape(value) {
    return value && typeof value === 'object' && typeof value.code === 'string' && /^\d{8}$/.test(value.code) && Number.isFinite(value.expires_at);
  }
  function paired() {
    const expiry = ui.state?.pairing_expires_at;
    return ui.state?.paired_mac === true && Number.isFinite(expiry) && expiry > now();
  }
  function phase() {
    if (!ui.online || Date.now() - ui.lastRead > 5000) return 'service';
    if (ui.state?.device_connected !== true) return 'device';
    if (!paired()) return validCode(ui.pairing) ? 'compare' : 'pair';
    if (ui.state?.local_ready !== true) return 'device';
    if (ui.state?.remote_enabled !== true) return 'gateway';
    if (ui.websiteLinked) return 'done';
    return validCode(ui.state.browser_pairing) ? 'website-code' : 'website';
  }
  function render() {
    const current = phase();
    for (const id of ['comparison', 'website-code-panel', 'pair', 'prepare-website', 'continue-website', 'website-link', 'access-details']) $(id).hidden = true;
    $('comparison-code').textContent = '';
    $('website-code').textContent = '';
    $('retry').hidden = !['service', 'device', 'gateway'].includes(current);
    $('retry').disabled = ui.busy;
    $('retry').textContent = current === 'gateway' ? 'Check website connection' : 'Check connection';
    const step = ['service', 'device'].includes(current) ? 1 : ['pair', 'compare'].includes(current) ? 2 : 3;
    for (const [index, id] of ['step-device', 'step-mac', 'step-web'].entries()) {
      $(id).removeAttribute('aria-current'); $(id).dataset.complete = String(index + 1 < step);
      if (index + 1 === step) $(id).setAttribute('aria-current', 'step');
    }
    let title, description, eyebrow;
    if (current === 'service') {
      eyebrow = 'MAC COMPANION'; title = ui.state ? 'Reconnect to your Mac.' : 'Checking your connection.';
      description = ui.state ? 'The Mac companion is not responding. Ask your setup agent to check that it is running, then retry here.' : 'Keep your gadget powered on. This page will show the next step.';
    } else if (current === 'device') {
      eyebrow = 'DEVICE CONNECTION'; title = paired() ? 'Your Mac access is saved.' : 'Looking for your Modulate.';
      description = 'Keep the gadget powered and on the same reachable network as this Mac. Your setup agent can check the device link. We’ll continue when it is online.';
    } else if (current === 'pair') {
      eyebrow = 'MAC ACCESS'; title = 'Let Modulate use this Mac.';
      description = 'Prepare a comparison code, then approve it on your gadget. Starting this step does not grant access.';
      $('pair').hidden = false; $('access-details').hidden = false;
    } else if (current === 'compare') {
      eyebrow = 'MAC ACCESS'; title = 'Compare both screens.';
      description = 'This code must match the one on your Modulate. It is different from the earlier device setup code.';
      $('comparison').hidden = false; $('comparison-code').textContent = ui.pairing.code;
      $('comparison-expiry').textContent = `Expires in ${remaining(ui.pairing.expires_at)}. A fresh code needs a new comparison.`;
      $('access-details').hidden = false;
    } else if (current === 'gateway') {
      eyebrow = 'WEBSITE CONNECTION'; title = 'One more connection step.';
      description = 'Your gadget and Mac are linked. Your setup agent still needs to connect this Mac to the Modulate website. Keep this page open and ask the agent to finish the website connection using your existing pairing.';
    } else if (current === 'website') {
      eyebrow = 'WEBSITE CONNECTION'; title = 'Finish connecting.';
      description = 'Your gadget and Mac are linked. Get a one-use code to connect this browser to your device on the website.';
      $('prepare-website').hidden = false;
    } else if (current === 'website-code') {
      eyebrow = 'WEBSITE CONNECTION'; title = 'Continue on the website.';
      description = 'Copy the code and paste it into Modulate’s connection form. The website will confirm when it connects.';
      $('website-code-panel').hidden = false; $('website-code').textContent = ui.state.browser_pairing.code;
      $('website-expiry').textContent = `Expires in ${remaining(ui.state.browser_pairing.expires_at)}. Used once, then gone.`;
      $('continue-website').hidden = false;
    } else {
      eyebrow = 'WEBSITE CONNECTION'; title = 'Continue on Modulate';
      description = 'A browser connection was added. The website will check this browser’s session.';
      $('website-link').hidden = false;
    }
    $('eyebrow').textContent = eyebrow; $('title').textContent = title; $('description').textContent = description;
    for (const id of ['pair', 'prepare-website', 'continue-website']) $(id).disabled = ui.busy;
    $('notice').hidden = !ui.error || current !== ui.errorPhase;
    $('notice').textContent = current === ui.errorPhase ? ui.error : '';
    if (current === 'website-code' && ui.clipboardFallback) $('website-link').hidden = false;
    const denied = [['screen_recording','Screen Recording'],['accessibility','Accessibility']]
      .filter(([key]) => ui.state?.native_permissions?.[key] === false).map(([,name]) => name);
    $('permission-note').hidden = !paired() || !denied.length || ['service','device'].includes(current);
    $('permission-note').textContent = denied.length ? `Computer control still needs ${denied.join(' and ')} permission on this Mac. Your agent can help with that; other features can still connect.` : '';
  }
  function apply(snapshot, pairing) {
    validateSnapshot(snapshot);
    if (pairing !== null && !codeShape(pairing)) throw Error('The Mac comparison state is incomplete.');
    if (ui.state?.browser_pairing?.code !== snapshot.browser_pairing?.code) ui.clipboardFallback = false;
    ui.state = snapshot; ui.pairing = pairing; ui.online = true; ui.lastRead = Date.now();
    if (snapshot.browser_count === 0) ui.websiteLinked = false;
    const browser = snapshot.browser_pairing;
    if (snapshot.local_ready !== true || snapshot.paired_mac !== true || snapshot.remote_enabled !== true) {
      ui.seenWebsite = null; ui.websiteLinked = false;
    } else if (validCode(browser)) {
      ui.seenWebsite = {expires_at: browser.expires_at, count: Number.isInteger(browser.browser_count) ? browser.browser_count : snapshot.browser_count};
    } else if (ui.seenWebsite && ui.seenWebsite.expires_at > now() && Number.isInteger(snapshot.browser_count) && snapshot.browser_count > ui.seenWebsite.count) {
      ui.websiteLinked = true; ui.seenWebsite = null;
    } else {
      // A disappeared offer without a new session may have been replaced or
      // revoked. A later unrelated browser must not complete this request.
      ui.seenWebsite = null;
    }
  }
  async function readCurrent() {
    try {
      const snapshot = validateSnapshot(await api('/api/setup'));
      const pairing = snapshot.paired_mac === true ? null : (await api('/api/pairing')).pending;
      if (pairing !== null && !codeShape(pairing)) throw Error('The Mac comparison state is incomplete.');
      return {snapshot, pairing};
    } catch (error) { error.readFailure = true; throw error; }
  }
  async function refresh() {
    if (ui.busy) return;
    const epoch = ++ui.epoch;
    try { const value = await readCurrent(); if (epoch !== ui.epoch) return; apply(value.snapshot, value.pairing); }
    catch { if (epoch !== ui.epoch) return; ui.online = false; ui.pairing = null; }
    render();
  }
  async function perform(kind) {
    if (ui.busy) return;
    ui.busy = true; ++ui.epoch; ui.error = ''; render();
    try {
      const fresh = await readCurrent(); apply(fresh.snapshot, fresh.pairing);
      if (kind === 'pair') {
        if (phase() === 'pair') await api('/api/setup/pairing', {});
      } else if (phase() === 'website' || phase() === 'website-code') {
        const response = await api('/api/setup/browser-code', {}); apply(response, null);
      }
      const latest = await readCurrent(); apply(latest.snapshot, latest.pairing);
    } catch (error) { if (error.readFailure) {ui.online = false; ui.pairing = null;} ui.error = error.message; ui.errorPhase = phase(); }
    finally { ui.busy = false; render(); }
  }
  $('pair').addEventListener('click', () => perform('pair'));
  $('prepare-website').addEventListener('click', () => perform('website'));
  $('retry').addEventListener('click', () => { ui.error = ''; refresh(); });
  $('continue-website').addEventListener('click', async () => {
    if (ui.busy || phase() !== 'website-code') return;
    ui.busy = true; ++ui.epoch; render();
    let copying = false;
    try {
      const fresh = await readCurrent(); apply(fresh.snapshot, fresh.pairing);
      if (phase() !== 'website-code') { render(); return; }
      copying = true;
      await navigator.clipboard.writeText(ui.state.browser_pairing.code);
      window.location.assign(website);
    } catch (error) {
      if (error.readFailure) {ui.online = false; ui.pairing = null;}
      ui.clipboardFallback = copying;
      ui.error = copying ? 'Copy the code shown above, then open Modulate to enter it.' : 'The current connection could not be verified. Check the Mac companion before continuing.';
      ui.errorPhase = phase();
    } finally { ui.busy = false; render(); }
  });
  async function poll() { await refresh(); pollTimer = setTimeout(poll, 1000); }
  (async () => {
    try { await renewSession(); await poll(); }
    catch { ui.error = 'The Mac companion is unavailable. Ask your setup agent to restart it, then refresh this page.'; ui.errorPhase = 'service'; render(); }
  })();
  setInterval(render, 1000); // Clear codes at expiry even if the next request stalls.
  window.addEventListener('pagehide', () => { clearTimeout(pollTimer); ++ui.epoch; });
})();
