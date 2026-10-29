import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity, ArrowRight, ArrowUpRight, AudioLines,
  Bell, Camera, Check, CheckCircle2, ChevronRight, CircleHelp, Code2, Command,
  Copy, Cpu, Gamepad2, KeyRound, LayoutDashboard, Library, Link2, Loader2,
  Menu, Mic, Monitor, MousePointer2, Power, Radio, RefreshCw, RotateCcw,
  Settings2, ShieldCheck, Smartphone, Sparkles, Square, Volume2, Wifi, X,
} from 'lucide-react';
import { command, connectApi, previewUrl } from './api';
import './connect.css';
import AppLibrary from './Library';
import metaLogo from './assets/meta.svg';

const NAV = [
  ['studio', LayoutDashboard, 'Studio'], ['library', Library, 'App library'], ['permissions', ShieldCheck, 'Permissions'],
  ['activity', Activity, 'Agent activity'], ['code', Code2, 'Code & checks'],
];
const PERMISSIONS = [
  { key: 'system', icon: Settings2, title: 'System controls', detail: 'Adjust the paired Mac’s volume, mute and supported display brightness.', tag: 'Mac companion' },
  { key: 'computer', icon: MousePointer2, title: 'Computer use', detail: 'Let the agent see your screen and use the cursor, keyboard and apps for your requests. Task screenshots go to Meta.', tag: 'Screen Recording + Accessibility' },
  { key: 'camera', icon: Camera, title: 'Mac camera', detail: 'Show your Mac’s live camera on Modulate’s screen, with generated effects.', tag: 'Camera permission' },
  { key: 'remote_preview', icon: Monitor, title: 'Camera preview in browsers', detail: 'Share the live camera preview with connected browsers through the encrypted cloud connection. Off keeps camera frames on the Mac and Pi.', tag: 'Optional sharing' },
  { key: 'audio', icon: AudioLines, title: 'Computer audio', detail: 'Play the paired Mac’s system audio through the speaker connected to Modulate.', tag: 'System audio recording' },
  { key: 'speaker', icon: Volume2, title: 'Spoken replies', detail: 'Read replies and errors aloud through the device speaker. Reply text is sent to ElevenLabs.', tag: 'Device speaker' },
  { key: 'voice', icon: Mic, title: 'Device microphone', detail: 'Use the microphone on Modulate for spoken requests and “Hey Meta” wake listening.', tag: 'Device microphone' },
  { key: 'hardware', icon: Cpu, title: 'Hardware setup', detail: 'Inspect modules and guide supported repairs. Physical steps still need your confirmation.', tag: 'Connected modules' },
];
const CONTROL_NAMES = { joystick: 'Joystick', encoder: 'Rotary knob', button_a: 'Button A', button_b: 'Button B', encoder_pressed: 'Knob press', pitft_buttons: 'Screen buttons' };
const dateMs = value => typeof value === 'number' ? (value < 1e12 ? value * 1000 : value) : Date.parse(value);
const human = value => String(value || '').replace(/_/g, ' ').replace(/^./, value => value.toUpperCase());
const pretty = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
const clock = value => { const date = new Date(dateMs(value)); return Number.isFinite(date.getTime()) ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''; };

function Button({ children, icon: Icon, primary, danger, quiet, className = '', ...props }) {
  return <button className={`mc-button ${primary ? 'mc-primary' : ''} ${danger ? 'mc-danger' : ''} ${quiet ? 'mc-quiet' : ''} ${className}`} {...props}>{Icon && <Icon size={16} aria-hidden="true" />}{children}</button>;
}
function Badge({ children, live, warning }) {
  return <span className={`mc-badge ${live ? 'is-live' : ''} ${warning ? 'is-warning' : ''}`}><span className="mc-dot" />{children}</span>;
}
function Toggle({ label, checked, disabled, onChange }) {
  return <button className={`mc-toggle ${checked ? 'is-on' : ''}`} type="button" role="switch" aria-label={label} aria-checked={Boolean(checked)} disabled={disabled} onClick={() => onChange(!checked)}><span /></button>;
}
function Card({ children, className = '', ...props }) {
  return <section className={`mc-card ${className}`} {...props}>{children}</section>;
}
function Brand({ small }) {
  return <span className={`mc-brand ${small ? 'mc-brand-small' : ''}`}><span className="mc-mark" aria-hidden="true"><i /><i /><i /></span>modulate<span className="mc-brand-period">.</span></span>;
}
function GadgetIllustration() {
  return <div className="mc-gadget-art" aria-hidden="true">
    <div className="mc-orbit mc-orbit-one" /><div className="mc-orbit mc-orbit-two" />
    <span className="mc-art-spark mc-art-spark-one">+</span><span className="mc-art-spark mc-art-spark-two">+</span>
    <div className="mc-art-wire mc-art-wire-one" /><div className="mc-art-wire mc-art-wire-two" />
    <div className="mc-art-knob"><div /><span /></div>
    <div className="mc-art-device"><div className="mc-art-device-top"><span>MODULATE</span><span>01</span></div><div className="mc-art-screen"><AudioLines size={48} strokeWidth={1.3} /><span>Hey Meta.</span></div><div className="mc-art-device-bottom"><i /><span /><span /></div></div>
    <div className="mc-art-button"><i /></div><div className="mc-art-caption"><span className="mc-dot" />One device. Your next idea.</div>
  </div>;
}

export default function Connect() {
  const [view, setView] = useState('studio');
  const [menuOpen, setMenuOpen] = useState(false);
  const [session, setSession] = useState(null);
  const [state, setState] = useState(null);
  const [online, setOnline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState('');
  const [code, setCode] = useState('');
  const [pairPermissions, setPairPermissions] = useState(() => Object.fromEntries(PERMISSIONS.map(({ key }) => [key, key !== 'remote_preview'])));
  const [request, setRequest] = useState('');
  const [showVoiceHelp, setShowVoiceHelp] = useState(false);
  const [draftText, setDraftText] = useState('');
  const [now, setNow] = useState(Date.now());
  const [pairing, setPairing] = useState(null);
  const [inspectSource, setInspectSource] = useState('active');
  const [inspectView, setInspectView] = useState('code');
  const [previewError, setPreviewError] = useState(false);
  const [copied, setCopied] = useState(false);
  const [dismissedResponse, setDismissedResponse] = useState(null);
  const mounted = useRef(true);
  const refreshTask = useRef(null);
  const refreshGeneration = useRef(0);
  const mutationRunning = useRef(false);
  const requestRef = useRef(null);
  const pairingRef = useRef(null);
  const draftIdRef = useRef(null);
  const authenticated = session?.connected === true;
  const deviceConnected = online && state?.device?.connected === true;
  const agentRunning = state?.agent?.running === true;
  const permissions = session?.permissions || state?.permissions || {};
  const voiceDraftId = state?.voice_draft?.job_id || null;
  const voiceDraftText = state?.voice_draft?.text || '';
  const voiceDraftEditing = state?.voice_draft?.editing === true;

  useEffect(() => {
    const previousTitle = document.title;
    const previousIcon = document.querySelector('link[rel="icon"]');
    const previousIconHref = previousIcon?.getAttribute('href');
    const icon = previousIcon || document.createElement('link');
    icon.setAttribute('rel', 'icon');
    icon.setAttribute('href', `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#101113"/><g fill="#469dff"><rect x="6" y="12" width="5" height="13" rx="1.5"/><rect x="14" y="6" width="5" height="19" rx="1.5"/><rect x="22" y="9" width="5" height="16" rx="1.5"/></g></svg>')}`);
    if (!previousIcon) document.head.appendChild(icon);
    document.title = 'Modulate Connect — Your hardware, a new idea';
    document.body.classList.add('modulate-connect-page');
    return () => {
      document.title = previousTitle;
      document.body.classList.remove('modulate-connect-page');
      if (!previousIcon) icon.remove();
      else if (previousIconHref === null) icon.removeAttribute('href');
      else icon.setAttribute('href', previousIconHref);
    };
  }, []);

  const refresh = useCallback(() => {
    if (mutationRunning.current || !mounted.current) return Promise.resolve();
    const generation = refreshGeneration.current;
    if (refreshTask.current?.generation === generation) return refreshTask.current.promise;
    // A mutation starts a new generation; an older poll cannot restore revoked access.
    const task = { generation, promise: null };
    const isCurrent = () => mounted.current && generation === refreshGeneration.current;
    refreshTask.current = task;
    task.promise = (async () => {
      let nextSession;
      try {
        const current = await connectApi('session');
        if (!isCurrent()) return;
        nextSession = current.session || current;
        if (nextSession.connected) {
          const result = await connectApi('state');
          if (!isCurrent()) return;
          setSession(nextSession);
          setState(result.state || result);
          setOnline(nextSession.companion?.online !== false);
        } else {
          setSession(nextSession);
          setState(null);
          setOnline(false);
        }
      } catch (error) {
        if (!isCurrent()) return;
        setOnline(false);
        if (error.status === 401) { setSession(null); setState(null); }
        else if (nextSession) setSession(nextSession);
      } finally {
        if (refreshTask.current === task) refreshTask.current = null;
        if (isCurrent()) setLoading(false);
      }
    })();
    return task.promise;
  }, []);

  useEffect(() => {
    mounted.current = true;
    let timer;
    let stopped = false;
    const poll = async () => { await refresh(); if (!stopped) timer = setTimeout(poll, document.hidden ? 8000 : 1500); };
    poll();
    const onVisibility = () => { if (!document.hidden) refresh(); };
    document.addEventListener('visibilitychange', onVisibility);
    return () => { stopped = true; mounted.current = false; refreshGeneration.current += 1; clearTimeout(timer); document.removeEventListener('visibilitychange', onVisibility); };
  }, [refresh]);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(timer); }, []);
  useEffect(() => {
    if (!voiceDraftEditing || voiceDraftId !== draftIdRef.current) setDraftText(voiceDraftText);
    draftIdRef.current = voiceDraftId;
  }, [voiceDraftId, voiceDraftText, voiceDraftEditing]);
  useEffect(() => { setPreviewError(false); }, [state?.active?.revision, state?.preview_version, permissions.remote_preview]);
  useEffect(() => { if (state?.paired && pairing) setPairing(null); }, [state?.paired, pairing]);
  useEffect(() => {
    if (!pairing) return;
    const previousFocus = document.activeElement;
    pairingRef.current?.querySelector('button')?.focus();
    const keydown = event => {
      if (event.key === 'Escape') { setPairing(null); return; }
      if (event.key !== 'Tab') return;
      const focusable = pairingRef.current?.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),[tabindex="0"]');
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => { document.removeEventListener('keydown', keydown); if (previousFocus?.isConnected) previousFocus.focus(); };
  }, [pairing]);

  const run = async (key, fn, success) => {
    if (busy || mutationRunning.current) return null;
    mutationRunning.current = true;
    refreshGeneration.current += 1;
    setBusy(key); setNotice(null);
    try {
      const result = await fn();
      if (!mounted.current) return null;
      if (key === 'disconnect') {
        setSession(null); setState(null); setOnline(false);
        setRequest(''); setDraftText(''); setPairing(null); setDismissedResponse(null);
      }
      if (success) setNotice({ text: success, type: 'success' });
      return result;
    } catch (error) {
      if (mounted.current) setNotice({ text: error.message || 'That action could not be completed.', type: 'error' });
      return null;
    } finally {
      mutationRunning.current = false;
      await refresh();
      if (mounted.current) setBusy('');
    }
  };
  const act = (key, path, payload, success) => run(key, () => command(path, payload), success);
  const navigate = next => { setView(next); setMenuOpen(false); };
  const sendRequest = async event => {
    event?.preventDefault();
    const text = request.trim();
    if (!text || !deviceConnected || agentRunning) return;
    const result = await act('request', '/api/request', { text, followup_id: state?.clarification?.id || null });
    if (result) setRequest('');
  };
  const pairBrowser = async event => {
    event.preventDefault();
    const result = await run('connect', () => connectApi('session', { code: code.trim(), name: 'Modulate web browser', permissions: pairPermissions }));
    if (result) { setCode(''); setView('studio'); }
  };
  const createDevicePairing = async () => {
    const result = await act('pair', '/api/pairing', {});
    if (result?.code) setPairing(result);
  };
  const togglePermission = async (key, enabled) => {
    await run(`permission-${key}`, () => connectApi('permissions', { permissions: { [key]: enabled } }));
  };
  const chooseExample = text => { setView('studio'); setRequest(text); requestAnimationFrame(() => requestRef.current?.focus()); };
  const active = state?.active;
  const packageData = active?.package;
  const controls = Array.isArray(state?.device?.capabilities?.controls) ? state.device.capabilities.controls : [];
  const connectionStatus = loading ? 'Connecting' : !authenticated ? 'Not connected' : !online ? 'Companion offline' : !deviceConnected ? 'Device offline' : 'Connected';
  const connectionHint = loading ? 'Checking your connection…' : !authenticated ? 'Enter a code to link this browser.' : !online ? 'Open Modulate Studio on your Mac.' : !deviceConnected ? 'Companion is online. Check your Pi.' : `${controls.length} ${controls.length === 1 ? 'control' : 'controls'} ready to use.`;
  const response = state?.response;
  const responseVisible = response?.text && response.id !== dismissedResponse && dateMs(response.expires_at) > now;
  const draft = state?.voice_draft;
  const draftSeconds = draft?.send_at ? Math.max(0, Math.ceil((dateMs(draft.send_at) - now) / 1000)) : null;
  const computer = state?.computer;
  const approval = computer?.pending_approval;
  const speaker = state?.device?.telemetry?.speaker;
  const hardware = state?.hardware;
  const workflow = hardware?.workflow;
  const repairActive = workflow && !['complete', 'completed', 'cancelled'].includes(workflow.phase);
  const budget = state?.budget;
  const eventList = Array.isArray(state?.events) ? [...state.events].reverse() : [];
  const selected = state?.[inspectSource];
  const selectedPackage = selected?.package;
  const checkEvent = eventList.find(event => event.tool === 'test_package' && event.detail && typeof event.detail === 'object' && (!selected?.revision || event.detail.candidate_id === selected.revision));
  const inspectContent = inspectView === 'code' ? selectedPackage?.code || selectedPackage || 'No program to inspect yet.' : inspectView === 'assets' ? selectedPackage?.assets || 'No generated sprite assets in this package.' : selected?.report || selected?.checks || checkEvent?.detail || 'No verification report available for this package yet.';
  const cameraRunning = state?.camera?.running === true;
  const cameraPreviewPrivate = Boolean(packageData?.camera) && permissions.remote_preview !== true;
  const audioRunning = state?.computer_audio?.running === true;
  const stateReady = authenticated && online;
  const genericDisabled = !stateReady || Boolean(busy);
  const pageTitles = {
    studio: ['Your device studio', 'A new idea is all it takes.'],
    library: ['Your app library', 'Return to something you love.'],
    permissions: ['You’re in control', 'Choose what Modulate can access. Change it anytime.'],
    activity: ['Inside the agent', 'Real decisions, tool calls and checks as they happen.'],
    code: ['Code & checks', 'The actual generated package, with its verification results.'],
    setup: ['Get connected', 'A simple path from your device to your everyday computer.'],
  };

  const pairingChoices = <fieldset className="mc-pair-permissions"><legend>CHOOSE DEVICE ACCESS</legend><div>{PERMISSIONS.map(({ key, title, detail }) => <label key={key} title={detail}><input type="checkbox" checked={pairPermissions[key]} onChange={event => setPairPermissions(previous => ({ ...previous, [key]: event.target.checked }))} /><span>{title}</span></label>)}</div><p>These settings apply to your Modulate across voice and connected browsers. Computer-task screenshots may go to Meta; spoken reply text goes to ElevenLabs.</p></fieldset>;

  const renderEvents = (compact = false) => <div className={`mc-timeline ${compact ? 'mc-timeline-compact' : ''}`}>
    {!eventList.length ? <div className="mc-empty"><Activity size={26} /><strong>Every idea starts here</strong><p>Your agent’s activity appears after your first request.</p></div> : eventList.slice(0, compact ? 7 : 80).map((event, index) => {
      const error = /fail|error|reject|cancel/.test(`${event.type} ${event.status}`);
      return <div className={`mc-event ${error ? 'mc-event-error' : ''}`} key={`${event.at}-${event.type}-${index}`}><span className="mc-event-marker" /><div className="mc-event-top"><span>{event.role ? human(event.role) : 'Studio'}</span><time>{clock(event.at)}</time></div><p>{event.title || human(event.tool || event.type)}</p>{event.detail && <details><summary>View {error ? 'details' : 'result'}</summary><pre>{pretty(event.detail).slice(0, 10000)}</pre></details>}</div>;
    })}
  </div>;

  const renderHardware = () => <Card className="mc-hardware-card">
    <div className="mc-card-heading"><h2>Connected modules</h2><Cpu size={18} /></div>
    {controls.length ? <div className="mc-controls">{controls.map(control => <div key={control} className={`mc-control ${state?.device?.input?.[control] === true ? 'mc-control-active' : ''}`}><span className="mc-dot" /><span>{CONTROL_NAMES[control] || human(control)}</span><small>{control === 'joystick' && Number.isFinite(state.device.input?.joystick_x) ? `${state.device.input.joystick_x.toFixed(1)} / ${state.device.input.joystick_y?.toFixed(1) ?? '—'}` : control === 'encoder' && Number.isFinite(state.device.input?.encoder_delta) ? `Δ ${state.device.input.encoder_delta}` : state.device.input?.[control] === true ? 'Pressed' : 'Ready'}</small></div>)}</div> : <p className="mc-muted mc-small">Verified modules appear when the device connects.</p>}
    {state?.device?.capabilities?.warnings?.length > 0 && <details className="mc-detail"><summary>Device notes ({state.device.capabilities.warnings.length})</summary>{state.device.capabilities.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</details>}
    {hardware?.report && <p className="mc-small mc-muted mc-bus-scan">{hardware.report.bus_available ? `Last scan: ${(hardware.report.addresses || []).map(address => `0x${address.toString(16).padStart(2, '0')}`).join(' · ') || 'No response'}` : 'The last scan could not read the bus.'}</p>}
    <Button quiet icon={RefreshCw} disabled={genericDisabled || agentRunning || !deviceConnected} onClick={() => act('hardware', '/api/request', { text: 'Check my connected hardware and explain any problems. Do not change addresses.' })}>Check hardware</Button>
    {repairActive && <div className="mc-repair"><span className="mc-eyebrow">{human(workflow.phase)}</span><p>{Array.isArray(workflow.instructions) ? workflow.instructions.join('\n') : workflow.instructions}</p>{workflow.required_phrase && <p className="mc-small mc-muted">When finished, say “Hey Meta, {workflow.required_phrase}.”</p>}{workflow.confirmation_step && <Button primary disabled={genericDisabled || agentRunning || !deviceConnected || !workflow.reboot_observed || workflow.confirmation_received} onClick={() => act('hardware-confirm', '/api/hardware/confirm', { id: workflow.id, step: workflow.confirmation_step })}>I completed this step</Button>}<Button quiet danger disabled={genericDisabled} onClick={() => act('hardware-cancel', '/api/hardware/cancel', {})}>Cancel setup</Button></div>}
  </Card>;

  return <div className="mc-app">
    <a className="mc-skip" href="#mc-main">Skip to content</a>
    <div className={`mc-sidebar-backdrop ${menuOpen ? 'is-open' : ''}`} onClick={() => setMenuOpen(false)} />
    <aside className={`mc-sidebar ${menuOpen ? 'is-open' : ''}`} id="mc-navigation">
      <a href="/connect" className="mc-brand-link" aria-label="Modulate home"><Brand /></a>
      <button className="mc-sidebar-close" type="button" aria-label="Close navigation" onClick={() => setMenuOpen(false)}><X size={22} /></button>
      <div className="mc-workspace"><span className="mc-workspace-icon"><Cpu size={19} /></span><div><strong>Device workspace</strong><span>{authenticated ? session?.companion?.name || 'Connected companion' : 'Connect your Modulate'}</span></div><ChevronRight size={16} /></div>
      <span className="mc-nav-label">WORKSPACE</span>
      <nav aria-label="Modulate workspace">{NAV.map(([key, Icon, label]) => <button key={key} className={view === key ? 'is-selected' : ''} aria-current={view === key ? 'page' : undefined} onClick={() => navigate(key)}><Icon size={21} /><span>{label}</span>{key === 'activity' && agentRunning && <span className="mc-nav-busy" />}</button>)}</nav>
      <div className="mc-sidebar-divider" />
      <button className={`mc-nav-help ${view === 'setup' ? 'is-selected' : ''}`} onClick={() => navigate('setup')}><CircleHelp size={21} />Setup guide<ArrowUpRight size={15} /></button>
      <div className="mc-sidebar-bottom">
        <section className="mc-sidebar-device" aria-label="Device connection">
          <div className="mc-sidebar-device-top"><span className="mc-device-mini"><Cpu size={19} /></span><strong>{authenticated ? state?.device?.name || 'Your Modulate' : 'Your Modulate'}</strong></div>
          <div className="mc-connection-summary" role="status"><Badge live={!loading && authenticated && deviceConnected} warning={!loading && authenticated && !deviceConnected}>{connectionStatus}</Badge><p>{connectionHint}</p></div>
          {authenticated ? <Button quiet icon={Power} onClick={() => run('disconnect', () => connectApi('disconnect', {}), 'This browser has been disconnected.')} disabled={Boolean(busy)}>Disconnect browser</Button> : <Button quiet icon={Link2} onClick={() => navigate('studio')} disabled={loading}>Connect a device<ArrowRight size={14} /></Button>}
        </section>
      </div>
    </aside>

    <div className="mc-main-shell">
      <main className="mc-main" id="mc-main">
        <div className="mc-page-heading"><div className="mc-page-title"><button className="mc-menu-button" type="button" aria-label="Open navigation" aria-expanded={menuOpen} aria-controls="mc-navigation" onClick={() => setMenuOpen(true)}><Menu size={22} /></button><div><h1>{pageTitles[view][0]}</h1><p>{pageTitles[view][1]}</p></div></div>{authenticated && <Button icon={RefreshCw} quiet disabled={Boolean(busy)} onClick={refresh}>Refresh</Button>}</div>
        {notice && <div className={`mc-notice mc-notice-${notice.type}`} role="status">{notice.type === 'success' ? <CheckCircle2 size={18} /> : <Bell size={18} />}<span>{notice.text}</span><button aria-label="Dismiss notification" onClick={() => setNotice(null)}><X size={16} /></button></div>}
        {authenticated && !online && <div className="mc-notice mc-notice-warning" role="status"><Wifi size={18} /><span>Your companion is offline. Keep Modulate Studio running on the paired Mac. Retrying automatically.</span></div>}
        {computer?.active && <div className="mc-live-control" role="status"><span className="mc-pulse-dot" /><strong>Modulate is using your Mac</strong><span>{computer.scope || 'Paired Mac desktop'}</span><Button danger icon={Square} onClick={() => act('computer', '/api/computer', { action: 'revoke' })} disabled={genericDisabled}>Pause access</Button></div>}

        {!authenticated && view === 'studio' && <>
          <Card className="mc-welcome"><div className="mc-welcome-copy"><span className="mc-eyebrow"><Sparkles size={14} />YOUR HARDWARE. YOUR IMAGINATION.</span><h2>One connection.<br />A world of possibilities.</h2><p>Make a game. Control your computer. Give the same buttons and knob a completely new job.</p><div className="mc-welcome-foot"><span><Check size={14} />Your choice of permissions</span><span><Check size={14} />Disconnect anytime</span></div></div><GadgetIllustration /></Card>
          <div className="mc-connect-grid"><Card className="mc-pair-card"><div className="mc-section-icon"><Link2 size={24} /></div><h2>Let’s connect your device</h2><p>Enter the connection code from Modulate Studio on the Mac running your companion.</p><form onSubmit={pairBrowser}><label htmlFor="mc-connect-code">CONNECTION CODE</label><div className="mc-pair-input"><KeyRound size={19} /><input id="mc-connect-code" autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{8}" placeholder="8-digit connection code" value={code} maxLength={8} onChange={event => setCode(event.target.value.replace(/\D/g, '').slice(0, 8))} required /></div>{pairingChoices}<Button primary type="submit" disabled={code.length !== 8 || Boolean(busy)} icon={busy === 'connect' ? Loader2 : Link2}>{busy === 'connect' ? 'Connecting…' : 'Connect to Modulate'}{busy !== 'connect' && <ArrowRight size={17} />}</Button></form><p className="mc-pair-note"><ShieldCheck size={15} />The code gives this browser access to your device’s Studio.</p><button className="mc-text-link" onClick={() => navigate('setup')}>First time here? Set up your companion <ArrowUpRight size={14} /></button></Card>
          <Card className="mc-how-card"><h2>A few steps, then anything</h2><ol><li><span>1</span><div><strong>Start your companion</strong><p>Open Modulate Studio on your Mac. Keep it running to connect your device and computer.</p></div><Monitor size={22} /></li><li><span>2</span><div><strong>Choose your permissions</strong><p>Decide what the agent can use, from volume controls to your Mac’s camera.</p></div><ShieldCheck size={22} /></li><li><span>3</span><div><strong>Say what it should become</strong><p>“Hey Meta, make a kart racer.” The agent builds, checks and activates your idea.</p></div><Mic size={22} /></li></ol><div className="mc-mobile-note"><Smartphone size={21} /><p>On your phone? Use this page as a remote for the same connected device. Computer controls run on your paired Mac.</p></div></Card></div>
          <div className="mc-idea-row"><span>IMAGINE THE POSSIBILITIES</span><div><Gamepad2 size={18} /><span>“Make a kart racer”</span></div><div><Volume2 size={18} /><span>“Control my Mac volume”</span></div><div><Camera size={18} /><span>“Give my camera a fun twist”</span></div></div>
        </>}

        {authenticated && view === 'studio' && <>
          <div className="mc-stats"><Card><span className="mc-stat-icon"><Cpu size={20} /></span><div><span>Device</span><strong>{deviceConnected ? 'Connected' : 'Offline'}</strong><small>{state?.device?.name || 'Waiting for device'}</small></div></Card><Card><span className="mc-stat-icon"><Sparkles size={20} /></span><div><span>Agent</span><strong>{agentRunning ? 'Working' : state?.clarification ? 'Waiting for you' : 'Ready'}</strong><small>{agentRunning ? state?.agent?.title || human(state?.agent?.phase) : state?.model || 'Meta-powered'}</small></div></Card><Card><span className="mc-stat-icon"><Radio size={20} /></span><div><span>Voice</span><strong>{state?.wake ? 'Hey Meta is on' : 'Push to talk'}</strong><small>{human(state?.device?.telemetry?.voice?.state) || 'Awaiting microphone'}</small></div></Card></div>
          <div className="mc-studio-grid"><div className="mc-workspace-column">
            <Card className="mc-preview-card"><div className="mc-card-heading"><div><span className="mc-eyebrow">ON YOUR DEVICE</span><h2>{audioRunning ? 'Mac speaker' : active?.title || packageData?.title || 'Your next idea'}</h2></div><Badge live={deviceConnected && Boolean(active)}>{agentRunning ? 'Processing' : audioRunning ? 'Computer audio' : packageData?.camera ? 'Camera app' : active ? human(active.kind || packageData?.kind) : 'Ready'}</Badge></div><div className="mc-preview-stage"><div className="mc-screen-device"><div className="mc-screen-top"><Brand small /><span>240 × 135</span></div><div className="mc-screen-frame">{audioRunning ? <div className="mc-screen-empty"><AudioLines size={46} /><strong>Your Mac, through Modulate</strong><p>{state?.device?.telemetry?.computer_audio?.error || 'Play something on your Mac.'}</p></div> : (active?.kind || packageData?.kind) === 'control' ? <div className="mc-screen-empty mc-control-screen"><Volume2 size={32} /><strong>{state?.volume?.muted ? 'Muted' : Number.isFinite(state?.volume?.volume) ? `${Math.round(state.volume.volume)}%` : Number.isFinite(state?.volume?.brightness) ? `${Math.round(state.volume.brightness)}%` : 'Control mode'}</strong><p>Paired Mac · {Number.isFinite(state?.volume?.brightness) ? 'brightness' : 'system volume'}</p></div> : active && !previewError && !cameraPreviewPrivate ? <img src={previewUrl(`${active.revision}:${state?.preview_version || 'initial'}`)} alt="Actual host-rendered preview of the active Modulate program" width="240" height="135" onError={() => setPreviewError(true)} /> : <div className="mc-screen-empty"><Sparkles size={35} /><strong>{cameraPreviewPrivate ? 'Camera preview is private' : previewError ? 'Preview unavailable' : 'Ready for an idea.'}</strong><p>{cameraPreviewPrivate ? 'Allow browser camera preview in Permissions to see it here.' : previewError ? 'Your active program is retained.' : 'Your program will appear here.'}</p></div>}{agentRunning && <div className="mc-preview-processing"><Loader2 size={20} className="mc-spin" /><span>{state?.agent?.title || 'Processing your request'}</span></div>}</div><div className="mc-screen-bottom"><span className="mc-dot" /><span>PROGRAMMABLE BY YOU</span><span>▰ ▰ ▰</span></div></div></div><div className="mc-preview-footer"><span><span className="mc-dot" />{audioRunning ? 'Mac → Pi audio status' : 'Host preview · actual program output'}</span><code>{active?.revision ? `REV ${active.revision.slice(0, 8).toUpperCase()}` : 'REV —'}</code></div></Card>
            {responseVisible && <Card className="mc-response"><div><Sparkles size={19} /><h2>Modulate replied</h2><Button quiet disabled={genericDisabled} onClick={async () => { if (await act('response', '/api/response/dismiss', { id: response.id })) setDismissedResponse(response.id); }}>Dismiss</Button></div><p aria-live="polite">{response.text}</p></Card>}
            {draft && <Card className="mc-draft"><div className="mc-card-heading"><h2>Review your spoken request</h2><Badge>{draft.editing ? 'Sending paused' : draftSeconds === 0 ? 'Sending…' : `Sending in ${draftSeconds ?? '—'}s`}</Badge></div><label className="mc-sr-only" htmlFor="mc-draft">Spoken request</label><textarea id="mc-draft" value={draftText} readOnly={!draft.editing} maxLength={2000} onChange={event => setDraftText(event.target.value)} /><div className="mc-draft-actions"><Button quiet disabled={genericDisabled} onClick={() => act('draft', '/api/draft', { job_id: draft.job_id, action: 'discard' })}>Discard</Button>{!draft.editing && <Button disabled={genericDisabled || draftSeconds === 0} onClick={() => act('draft', '/api/draft', { job_id: draft.job_id, action: 'pause' })}>Edit</Button>}<Button primary disabled={genericDisabled || !draftText.trim() || (!draft.editing && draftSeconds === 0)} onClick={() => act('draft', '/api/draft', { job_id: draft.job_id, action: 'send', text: draftText.trim() })}>Send now<ArrowUpRight size={15} /></Button></div></Card>}
            <Card className="mc-composer">{state?.clarification && <div className="mc-clarification"><span className="mc-eyebrow">{state.clarification.kind === 'recovery' ? 'LET’S GET THIS WORKING' : 'ONE QUICK QUESTION'}</span><p>{state.clarification.question}</p><span>Answer directly after the question. No “Hey Meta” needed.</span><Button quiet disabled={genericDisabled} onClick={() => act('cancel', '/api/cancel', {})}>Keep current app</Button></div>}<form onSubmit={sendRequest}><label htmlFor="mc-request"><Sparkles size={18} />{state?.clarification ? 'Your answer' : 'What should it become?'}</label><textarea id="mc-request" ref={requestRef} value={request} onChange={event => setRequest(event.target.value)} onKeyDown={event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); sendRequest(); } }} maxLength={4000} rows={3} placeholder={state?.clarification ? 'Reply here…' : 'Make an original kart racer. Use the joystick to steer and button A to boost…'} /><div className="mc-composer-bottom"><button type="button" className="mc-voice-help" onClick={() => setShowVoiceHelp(!showVoiceHelp)} aria-expanded={showVoiceHelp}><AudioLines size={18} />Device microphone</button><span className="mc-shortcut"><Command size={11} /> Enter</span><Button type="submit" primary disabled={!deviceConnected || agentRunning || Boolean(busy) || !request.trim()}>Send request<ArrowUpRight size={17} /></Button></div></form>{showVoiceHelp && <p className="mc-voice-instructions">Say “Hey Meta,” or hold both small screen buttons, then speak into the device microphone. Three seconds of silence finishes your request. You have another three seconds to choose Edit here before it sends. Answer follow-up questions directly within 20 seconds. Say “Hey Meta, cancel rebuild” to stop. This page does not record your browser microphone.</p>}<div className="mc-examples"><span>TRY</span><button onClick={() => chooseExample('Create an original kart racer')}>A kart racer<ArrowUpRight size={12} /></button><button onClick={() => chooseExample('Use the knob for my Mac volume')}>Mac volume<ArrowUpRight size={12} /></button><button onClick={() => chooseExample('Show my Mac camera with a fun visual twist')}>Camera remix<ArrowUpRight size={12} /></button></div></Card>
            <div className="mc-workspace-foot"><p>{agentRunning ? 'Your current app is preserved while the agent works.' : 'Generated, checked, then activated on your device.'}</p><Button quiet icon={RotateCcw} disabled={genericDisabled || agentRunning || !active?.previous} onClick={() => act('rollback', '/api/rollback', {})}>Restore previous</Button></div>
          </div><aside className="mc-activity-column"><Card className="mc-agent-card"><div className="mc-card-heading"><h2>Inside the agent</h2><Badge live={!agentRunning}>{agentRunning ? 'Working' : 'Ready'}</Badge></div><div className="mc-agent-summary"><span className="mc-agent-symbol"><Sparkles size={22} /></span><div><strong>{agentRunning ? state?.agent?.title || 'Processing your request' : state?.agent?.status === 'failed' ? 'The last request stopped' : 'Ready for your next idea'}</strong><p>{agentRunning ? [human(state?.agent?.role), human(state?.agent?.tool)].filter(Boolean).join(' · ') || 'Choosing the next step' : state?.agent?.summary || 'Follow the work as it happens.'}</p></div></div>{agentRunning && <Button danger icon={Square} disabled={genericDisabled} onClick={() => act('cancel', '/api/cancel', {})}>Cancel request</Button>}{renderEvents(true)}<button className="mc-card-footer-link" onClick={() => navigate('activity')}>View all activity<ArrowRight size={15} /></button></Card>{renderHardware()}</aside></div>
          <div className="mc-services-grid"><Card><div className="mc-card-heading"><h2>Your Mac</h2><Monitor size={20} /></div><Badge live={state?.paired}>{state?.paired ? 'Paired' : 'Not paired'}</Badge><p className="mc-service-description">{state?.paired ? 'Native controls run through your Mac companion.' : 'Link the device to this companion to enable Mac controls.'}</p>{Number.isFinite(state?.volume?.volume) && <div className="mc-volume-readout"><span>System volume</span><strong>{state.volume.muted ? 'Muted' : `${state.volume.volume}%`}</strong><div><i style={{ width: `${Math.max(0, Math.min(100, state.volume.volume))}%` }} /></div></div>}<div className="mc-inline-actions">{state?.paired ? <Button danger quiet disabled={genericDisabled} onClick={() => act('revoke', '/api/revoke', {})}>Revoke Mac pairing</Button> : <Button icon={Link2} disabled={genericDisabled} onClick={createDevicePairing}>Pair the device</Button>}<Button quiet onClick={() => navigate('permissions')}>Permissions<ArrowRight size={14} /></Button></div></Card>
          <Card><div className="mc-card-heading"><h2>Voice & speaker</h2><AudioLines size={20} /></div><div className="mc-setting-row"><div><strong>Wake listening</strong><span>{state?.device?.telemetry?.voice?.message || human(state?.device?.telemetry?.voice?.state) || 'Awaiting microphone'}</span></div><Toggle label="Wake listening" checked={state?.wake} disabled={genericDisabled || !deviceConnected} onChange={enabled => act('wake', '/api/wake', { enabled })} /></div><p className="mc-service-description">{state?.speech?.provider === 'elevenlabs' ? 'ElevenLabs' : state?.speech?.provider || 'Voice'} · {human(speaker?.state) || 'Awaiting speaker'}{state?.speech?.error || speaker?.error ? ` · ${state?.speech?.error || speaker?.error}` : ''}</p><div className="mc-inline-actions"><Button icon={Volume2} disabled={genericDisabled || !speaker?.available} onClick={() => act('speaker', '/api/speaker', { action: 'test' })}>Test speaker</Button><Button quiet danger disabled={genericDisabled || !speaker} onClick={() => act('speaker', '/api/speaker', { action: 'stop' })}>Stop audio</Button></div></Card>
          <Card><div className="mc-card-heading"><h2>Live connections</h2><Radio size={20} /></div><div className="mc-connection-row"><Camera size={18} /><div><strong>Mac camera</strong><span>{state?.camera?.error || (cameraRunning ? 'Live · Mac → Pi' : 'Starts when requested')}</span></div>{cameraRunning && <Button quiet danger onClick={() => act('camera', '/api/camera/stop', {})} disabled={genericDisabled}>Stop</Button>}</div><div className="mc-connection-row"><Volume2 size={18} /><div><strong>Computer audio</strong><span>{state?.computer_audio?.error || (audioRunning ? 'Streaming to Pi speaker' : 'Starts when requested')}</span></div>{audioRunning && <Button quiet danger onClick={() => act('audio', '/api/audio/stop', {})} disabled={genericDisabled}>Stop</Button>}</div><div className="mc-connection-row"><MousePointer2 size={18} /><div><strong>Computer use</strong><span>{computer?.error || (computer?.enabled ? 'Access follows Mac pairing' : computer?.paused ? 'Access paused' : 'Waiting for permissions')}</span></div>{computer?.enabled ? <Button quiet danger disabled={genericDisabled} onClick={() => act('computer', '/api/computer', { action: 'revoke' })}>Pause</Button> : computer?.paused ? <Button quiet disabled={genericDisabled || !computer?.supported} onClick={() => act('computer', '/api/computer', { action: 'enable' })}>Resume</Button> : null}</div></Card></div>
        </>}

        {view === 'permissions' && <>
          <Card className="mc-permission-banner"><span className="mc-section-icon"><ShieldCheck size={25} /></span><div><h2>Useful access. Always your choice.</h2><p>These choices apply to this device across voice and all connected browsers. Your Mac still asks for its own system permissions when needed.</p></div><Badge live={authenticated}>{authenticated ? 'Connection authenticated' : 'Connect to manage'}</Badge></Card>
          <div className="mc-permission-grid">{PERMISSIONS.map(({ key, icon: Icon, title, detail, tag }) => <Card className="mc-permission-card" key={key}><div className="mc-permission-top"><span className="mc-permission-icon"><Icon size={22} /></span><Toggle label={`Allow ${title.toLowerCase()}`} checked={permissions[key] === true} disabled={!authenticated || Boolean(busy)} onChange={enabled => togglePermission(key, enabled)} /></div><h2>{title}</h2><p>{detail}</p><div className="mc-permission-foot"><span>{tag}</span><strong className={permissions[key] ? 'is-enabled' : ''}>{!authenticated ? 'Not connected' : permissions[key] ? 'Allowed' : 'Off'}</strong></div></Card>)}</div>
          <div className="mc-permission-details"><Card><div className="mc-card-heading"><h2>Mac system permissions</h2><Monitor size={20} /></div><p className="mc-service-description">Open System Settings → Privacy & Security on the paired Mac. Allow the Modulate companion where prompted.</p><div className="mc-permission-status"><div><span>Screen Recording</span><Badge live={computer?.permissions?.screen_recording === true}>{computer?.permissions?.screen_recording === true ? 'Granted' : computer?.permissions?.screen_recording === false ? 'Required' : 'Not checked'}</Badge></div><div><span>Accessibility</span><Badge live={computer?.permissions?.accessibility === true}>{computer?.permissions?.accessibility === true ? 'Granted' : computer?.permissions?.accessibility === false ? 'Required' : 'Not checked'}</Badge></div><div><span>Camera / audio recording</span><span className="mc-muted mc-small">macOS prompts when needed</span></div></div>{computer?.error && <p className="mc-inline-error">{computer.error}</p>}</Card><Card><div className="mc-card-heading"><h2>Your recent context</h2><Sparkles size={20} /></div><p className="mc-service-description">Modulate uses recent requests to understand refinements like “make it louder.” Computer-task details are kept separately and briefly.</p><div className="mc-memory-stat"><strong>{state?.memory?.turns ?? '—'}</strong><span>recent requests{state?.memory?.hours ? ` · up to ${state.memory.hours} hours` : ''}</span></div><Button quiet icon={RotateCcw} disabled={genericDisabled || agentRunning || !state?.memory?.turns} onClick={() => act('memory', '/api/context/clear', {})}>Forget recent context</Button></Card></div>
          <div className="mc-privacy-note"><KeyRound size={18} /><p>Model and voice credentials stay on the server or companion. This browser never receives your API keys. A phone can operate this dashboard; it cannot grant control over iOS or Android system settings.</p></div>
        </>}

        {view === 'library' && (authenticated ? <AppLibrary library={state?.library} disabled={genericDisabled} running={agentRunning} deviceConnected={deviceConnected} now={now} onAction={act} /> : <Card className="mc-empty"><Library size={28} /><strong>Connect to see your apps</strong><Button onClick={() => navigate('studio')}>Connect your device</Button></Card>)}

        {view === 'activity' && <><div className="mc-activity-overview"><Card><span className="mc-eyebrow">CURRENT STATUS</span><h2>{agentRunning ? state?.agent?.title || 'Working on your request' : state?.clarification ? 'Waiting for your answer' : authenticated ? 'Ready for your next idea' : 'Connect to see activity'}</h2><p>{state?.agent?.summary || 'The agent decides which tools and specialist skills to use for each request.'}</p>{agentRunning && <Button danger icon={Square} disabled={genericDisabled} onClick={() => act('cancel', '/api/cancel', {})}>Cancel request</Button>}</Card><Card><span className="mc-eyebrow">PROVIDER USAGE</span><div className="mc-usage-number">{Number.isFinite(budget?.charged_or_reserved_dollars) ? `$${budget.charged_or_reserved_dollars.toFixed(3)}` : '—'}<span>{Number.isFinite(budget?.limit_dollars) ? ` / $${budget.limit_dollars.toFixed(0)}` : ''}</span></div><p>Reserved or used · {state?.provider || 'provider unavailable'}</p>{Number.isFinite(budget?.charged_or_reserved_dollars) && <div className="mc-usage-track"><span style={{ width: `${Math.min(100, budget.charged_or_reserved_dollars / budget.limit_dollars * 100)}%` }} /></div>}</Card></div><Card className="mc-full-activity"><div className="mc-card-heading"><h2>Activity timeline</h2><span className="mc-muted mc-small">Most recent first</span></div>{renderEvents()}</Card></>}

        {view === 'code' && <Card className="mc-code-card"><div className="mc-code-heading"><div className="mc-segmented">{['active', 'candidate'].map(source => <button key={source} className={inspectSource === source ? 'is-selected' : ''} aria-pressed={inspectSource === source} disabled={!state?.[source]} onClick={() => setInspectSource(source)}>{human(source)}</button>)}</div><span className="mc-read-only"><ShieldCheck size={14} />Read only</span></div><h2>{selected?.title || selectedPackage?.title || 'No package to inspect'}</h2><p className="mc-code-revision">{selected?.revision || 'Create an experience to see its source, assets and checks.'}</p><div className="mc-code-tabs" role="tablist" aria-label="Package details">{[['code', 'Source'], ['assets', 'Assets'], ['checks', 'Checks']].map(([key, label]) => <button key={key} id={`mc-tab-${key}`} role="tab" aria-selected={inspectView === key} aria-controls="mc-code-content" className={inspectView === key ? 'is-selected' : ''} onClick={() => setInspectView(key)}>{label}</button>)}<Button quiet icon={copied ? Check : Copy} disabled={!selectedPackage} onClick={async () => { try { await navigator.clipboard.writeText(pretty(inspectContent)); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch (_) { setNotice({ type: 'error', text: 'Clipboard unavailable. Select the source text to copy it.' }); } }}>{copied ? 'Copied' : 'Copy'}</Button></div><pre id="mc-code-content" role="tabpanel" aria-labelledby={`mc-tab-${inspectView}`} tabIndex={0}><code>{pretty(inspectContent)}</code></pre><div className="mc-code-footer">Generated applications run in the isolated device runtime. These are the actual package and recorded checks.</div></Card>}

        {view === 'setup' && <>
          <Card className="mc-setup-intro"><div><span className="mc-eyebrow">YOUR CONNECTION HUB</span><h2>Set up once.<br />Keep reinventing.</h2><p>Your Mac runs the companion. Your Modulate runs the hardware. This page brings them together from a computer or phone.</p></div><div className="mc-setup-diagram"><div><Monitor size={34} /><span>Mac companion</span></div><span className="mc-dotted-link" /><div><Link2 size={30} /><span>Modulate Connect</span></div><span className="mc-dotted-link" /><div><Cpu size={34} /><span>Modulate</span></div></div></Card>
          <div className="mc-setup-steps"><Card><span className="mc-step-number">01</span><h2>Run the Mac companion</h2><p>Use the Modulate companion installed on your Mac. Open its local Studio and keep it running while you use the device.</p><a className="mc-button" href="http://127.0.0.1:8787/" target="_blank" rel="noreferrer">Open local Studio<ArrowUpRight size={16} /></a><a className="mc-setup-source" href="https://github.com/Divyesh-Thirukonda/cruise/blob/codex/agentic-controller/context/product-runtime.md" target="_blank" rel="noreferrer">Companion installation guide<ArrowUpRight size={12} /></a><p className="mc-small mc-muted">This opens the companion on the computer you’re using. On a phone, do this step on your Mac.</p></Card><Card><span className="mc-step-number">02</span><h2>Link this browser</h2><p>In local Studio, create a web connection code. Return to this page and enter it to reach the same device workspace.</p><Button onClick={() => navigate('studio')} icon={KeyRound}>Enter connection code</Button><p className="mc-small mc-muted">Treat the code like a key to your device. You can disconnect a browser later.</p></Card><Card><span className="mc-step-number">03</span><h2>Choose your access</h2><p>Enable the capabilities you want. For cursor and keyboard control, grant Screen Recording and Accessibility to the companion in macOS.</p><Button onClick={() => navigate('permissions')} icon={ShieldCheck}>Manage permissions</Button><p className="mc-small mc-muted">Permission toggles do not bypass your Mac’s system permission prompts.</p></Card></div>
          <Card className="mc-support-card"><div><Monitor size={23} /><h2>Mac + Modulate</h2><p>Native system volume, cursor and keyboard, supported brightness, live camera and computer audio through the installed companion.</p></div><div><Smartphone size={23} /><h2>Phone or another browser</h2><p>Send requests, review speech, inspect the device, change permissions and follow builds. The paired Mac performs computer actions.</p></div></Card>
          <Card className="mc-faq"><h2>A few useful details</h2><details><summary>Does this work without the companion?<ChevronRight size={17} /></summary><p>The companion connects to your Pi and carries out native computer actions. Keep it running on the paired Mac. This page reconnects automatically when it comes back online.</p></details><details><summary>Does the browser get my API keys?<ChevronRight size={17} /></summary><p>No. Provider credentials are kept on the server or companion. Only an authenticated connection can send requests to your device.</p></details><details><summary>Can I stop it at any time?<ChevronRight size={17} /></summary><p>Cancel a request from Studio or say “Hey Meta, cancel rebuild.” Pause computer access, stop a camera or audio stream, or disconnect this browser from the relevant controls.</p></details></Card>
        </>}

        {approval && <Card className="mc-approval" role="status"><span className="mc-eyebrow">YOUR DECISION</span><h2>One action needs your approval</h2><p>{approval.description}</p><div><Button disabled={genericDisabled} onClick={() => act('approval', '/api/computer/approval', { id: approval.id, approved: false })}>Decline</Button><Button primary disabled={genericDisabled} onClick={() => act('approval', '/api/computer/approval', { id: approval.id, approved: true })}>Approve action</Button></div></Card>}
        <footer className="mc-footer"><div><img className="mc-footer-symbol" src={metaLogo} alt="" width={24} height={24} aria-hidden="true" /><span>Built with Meta AI</span>{authenticated && state?.model && <><span>·</span><span>{state.model}</span></>}</div><div>Connect. Create. Play.</div></footer>
      </main>
    </div>

    {pairing && <div className="mc-modal-backdrop"><section ref={pairingRef} className="mc-modal" role="dialog" aria-modal="true" aria-labelledby="mc-pairing-title"><button className="mc-modal-close" aria-label="Close pairing" onClick={() => setPairing(null)}><X size={20} /></button><span className="mc-section-icon"><Link2 size={25} /></span><h2 id="mc-pairing-title">Confirm on your Modulate</h2><p>Check that this code matches “Link this Mac?” on the device. Press small screen button A to allow, or B to decline.</p><output className="mc-physical-code">{dateMs(pairing.expires_at) <= now ? 'EXPIRED' : pairing.code}</output><p className="mc-small mc-muted">{Number.isFinite(dateMs(pairing.expires_at)) ? `Code expires at ${clock(pairing.expires_at)}` : 'One-time code · confirm on the device'}</p><Button primary disabled={Boolean(busy)} onClick={createDevicePairing}>Create a new code</Button></section></div>}
  </div>;
}
