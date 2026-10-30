'use client';

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
import './entry.css';
import AppLibrary from './Library';
import metaLogo from './assets/meta.svg';
import { usePathname, useRouter } from 'next/navigation';
import { Button, Badge, Toggle, Card, Brand } from './ui';
import { ConnectionLanding, SetupScreen, AccessStep, ConnectionUnavailable } from './EntryScreens';

const NAV = [
  ['studio', LayoutDashboard, 'Studio'], ['library', Library, 'App library'],
  ['device', Cpu, 'Device'], ['permissions', ShieldCheck, 'Access'],
];
const TOOLS = [['activity', Activity, 'Agent activity'], ['code', Code2, 'Code & checks']];
const ROUTES = { connect: '/connect', setup: '/connect/setup', access: '/connect/access', studio: '/connect/studio', library: '/connect/library', device: '/connect/device', permissions: '/connect/permissions', activity: '/connect/activity', code: '/connect/code' };
const routeView = path => Object.entries(ROUTES).find(([, route]) => route === path)?.[0] || 'connect';
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

export default function Connect() {
  const router = useRouter();
  const pathname = usePathname();
  const [view, setView] = useState(() => routeView(pathname));
  useEffect(() => { setView(routeView(pathname)); }, [pathname]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [session, setSession] = useState(null);
  const [state, setState] = useState(null);
  const [online, setOnline] = useState(false);
  const [connectionUnavailable, setConnectionUnavailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState('');
  const [code, setCode] = useState('');
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
        setConnectionUnavailable(nextSession.companion?.online === false);
      } catch (error) {
        if (!isCurrent()) return;
        setOnline(false);
        setConnectionUnavailable(error.status !== 401);
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
      if (mounted.current) {
        const setupHelp = !error.status || [502, 503, 504].includes(error.status);
        setNotice({ text: key === 'connect' && setupHelp ? 'Your Modulate connection isn’t reachable yet. Ask your setup agent to finish or reconnect it.' : error.message || 'That action could not be completed.', type: 'error', setupHelp });
      }
      return null;
    } finally {
      mutationRunning.current = false;
      await refresh();
      if (mounted.current) setBusy('');
    }
  };
  const act = (key, path, payload, success) => run(key, () => command(path, payload), success);
  const navigate = next => { setView(next); setMenuOpen(false); router.push(ROUTES[next]); };
  useEffect(() => {
    if (loading || busy === 'connect') return;
    if (authenticated && view === 'connect') { setView('studio'); router.replace(ROUTES.studio); }
    else if (!authenticated && !['connect', 'setup'].includes(view)) { setView('connect'); router.replace(ROUTES.connect); }
  }, [authenticated, loading, busy, view, router]);
  const sendRequest = async event => {
    event?.preventDefault();
    const text = request.trim();
    if (!text || !deviceConnected || agentRunning) return;
    const result = await act('request', '/api/request', { text, followup_id: state?.clarification?.id || null });
    if (result) setRequest('');
  };
  const pairBrowser = async event => {
    event.preventDefault();
    const result = await run('connect', () => connectApi('session', { code: code.trim(), name: 'Modulate web browser' }));
    if (result) { setCode(''); navigate('access'); }
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
  const connectionHint = loading ? 'Checking your connection…' : !authenticated ? 'Enter a code to link this browser.' : !online ? 'Check your device’s Wi-Fi and power.' : !deviceConnected ? 'AI service is online. Reconnecting to the controls.' : `${controls.length} ${controls.length === 1 ? 'control' : 'controls'} ready to use.`;
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
    studio: ['Studio', 'Your current app. Your next idea.'],
    library: ['Your app library', 'Return to something you love.'],
    permissions: ['Access', 'Only what you choose.'],
    activity: ['Inside the agent', 'Real decisions, tool calls and checks as they happen.'],
    code: ['Code & checks', 'The actual generated package, with its verification results.'],
    device: ['Your device', 'Connections, controls and sound.'],
    setup: ['Set up Modulate', 'Let your agent handle the setup.'],
    access: ['Choose access', 'Decide what Modulate can use.'],
    connect: ['Connect Modulate', 'Your next idea starts here.'],
  };

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

  const urgentControls = authenticated && (agentRunning || approval || draft || state?.clarification || computer?.active || cameraRunning || audioRunning) ? <div className="mf-urgent" role="status"><strong>{approval ? 'An action needs your approval' : draft ? 'Review your spoken request' : state?.clarification ? 'Modulate has a question' : agentRunning ? state?.agent?.title || 'Working on your request' : 'Your device is using a live connection'}</strong><div><Button quiet onClick={() => navigate('studio')}>Return to Studio</Button>{(agentRunning || draft || state?.clarification) && <Button danger disabled={genericDisabled} onClick={() => act('cancel', '/api/cancel', {})}>Cancel request</Button>}{computer?.active && <Button danger disabled={genericDisabled} onClick={() => act('computer', '/api/computer', { action: 'revoke' })}>Pause access</Button>}{cameraRunning && <Button quiet disabled={genericDisabled} onClick={() => act('camera', '/api/camera/stop', {})}>Stop camera</Button>}{audioRunning && <Button quiet disabled={genericDisabled} onClick={() => act('audio', '/api/audio/stop', {})}>Stop computer audio</Button>}</div></div> : null;
  const entryProps = { loading, busy, notice, connectionUnavailable, urgentControls, onDismissNotice: () => setNotice(null), navigate };
  const standalone = session?.companion?.platform !== 'darwin';
  if (view === 'setup') return <SetupScreen {...entryProps} standalone={standalone} connected={authenticated} />;
  if (!authenticated || view === 'connect') return <ConnectionLanding {...entryProps} standalone={standalone} code={code} setCode={setCode} onConnect={pairBrowser} />;
  if (view === 'access') return <AccessStep {...entryProps} permissions={permissions} choices={PERMISSIONS} online={online} onSave={async choices => {
    const result = await run('access', () => connectApi('permissions', { permissions: choices }));
    if (result) navigate('studio');
  }} />;

  return <div className="mc-app">
    <a className="mc-skip" href="#mc-main">Skip to content</a>
    <div className={`mc-sidebar-backdrop ${menuOpen ? 'is-open' : ''}`} onClick={() => setMenuOpen(false)} />
    <aside className={`mc-sidebar ${menuOpen ? 'is-open' : ''}`} id="mc-navigation">
      <a href="/connect" className="mc-brand-link" aria-label="Modulate home"><Brand /></a>
      <button className="mc-sidebar-close" type="button" aria-label="Close navigation" onClick={() => setMenuOpen(false)}><X size={22} /></button>
      <nav aria-label="Modulate workspace">{NAV.map(([key, Icon, label]) => <button key={key} className={view === key ? 'is-selected' : ''} aria-current={view === key ? 'page' : undefined} onClick={() => navigate(key)}><Icon size={21} /><span>{label}</span></button>)}</nav>
      <details className="mc-developer-nav" open={['activity', 'code'].includes(view) || undefined}><summary>Developer tools<ChevronRight size={14} /></summary><nav aria-label="Developer tools">{TOOLS.map(([key, Icon, label]) => <button key={key} className={view === key ? 'is-selected' : ''} aria-current={view === key ? 'page' : undefined} onClick={() => navigate(key)}><Icon size={18} /><span>{label}</span></button>)}</nav></details>
      <button className="mc-nav-help" onClick={() => navigate('setup')}><CircleHelp size={19} />Setup help<ArrowUpRight size={14} /></button>
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
        {authenticated && !online && <ConnectionUnavailable onSetup={() => navigate('setup')} />}
        {computer?.active && <div className="mc-live-control" role="status"><span className="mc-pulse-dot" /><strong>Modulate is using your Mac</strong><span>{computer.scope || 'Paired Mac desktop'}</span><Button danger icon={Square} onClick={() => act('computer', '/api/computer', { action: 'revoke' })} disabled={genericDisabled}>Pause access</Button></div>}

        {approval && <Card className="mc-approval" role="status"><span className="mc-eyebrow">YOUR DECISION</span><h2>One action needs your approval</h2><p>{approval.description}</p><div><Button disabled={genericDisabled} onClick={() => act('approval', '/api/computer/approval', { id: approval.id, approved: false })}>Decline</Button><Button primary disabled={genericDisabled} onClick={() => act('approval', '/api/computer/approval', { id: approval.id, approved: true })}>Approve action</Button></div></Card>}
        {agentRunning && <div className="mc-task-strip" role="status"><Loader2 size={18} className="mc-spin" /><div><strong>{state?.agent?.title || 'Working on your request'}</strong><span>{state?.agent?.summary || 'Your current app is kept while this builds.'}</span></div><Button quiet onClick={() => navigate('activity')}>Details</Button><Button danger icon={Square} disabled={genericDisabled} onClick={() => act('cancel', '/api/cancel', {})}>Cancel request</Button></div>}
        {view !== 'studio' && (draft || state?.clarification) && <div className="mc-task-strip" role="status"><Mic size={18} /><div><strong>{draft ? 'Review your spoken request' : 'Modulate has a question'}</strong><span>{draft ? draft.editing ? 'Sending is paused.' : 'Your request will send shortly.' : state.clarification.question}</span></div><Button primary onClick={() => navigate('studio')}>{draft ? 'Review request' : 'Answer'}</Button></div>}
        {(cameraRunning || audioRunning) && <div className="mc-active-streams">{cameraRunning && <Button quiet icon={Camera} disabled={genericDisabled} onClick={() => act('camera', '/api/camera/stop', {})}>Stop camera</Button>}{audioRunning && <Button quiet icon={Volume2} disabled={genericDisabled} onClick={() => act('audio', '/api/audio/stop', {})}>Stop computer audio</Button>}</div>}

        {authenticated && view === 'studio' && <>
          <p className="mc-voice-status"><Radio size={15} />{state?.wake ? 'Hey Meta is on' : 'Push to talk'}<span>Or type an idea below.</span></p>
          <div className="mc-studio-grid"><div className="mc-workspace-column">
            <Card className="mc-preview-card"><div className="mc-card-heading"><div><span className="mc-eyebrow">ON YOUR DEVICE</span><h2>{audioRunning ? 'Mac speaker' : active?.title || packageData?.title || 'Your next idea'}</h2></div><Badge live={deviceConnected && Boolean(active)}>{agentRunning ? 'Processing' : audioRunning ? 'Computer audio' : packageData?.camera ? 'Camera app' : active ? human(active.kind || packageData?.kind) : 'Ready'}</Badge></div><div className="mc-preview-stage"><div className="mc-screen-device"><div className="mc-screen-top"><Brand small /><span>240 × 135</span></div><div className="mc-screen-frame">{audioRunning ? <div className="mc-screen-empty"><AudioLines size={46} /><strong>Your Mac, through Modulate</strong><p>{state?.device?.telemetry?.computer_audio?.error || 'Play something on your Mac.'}</p></div> : (active?.kind || packageData?.kind) === 'control' ? <div className="mc-screen-empty mc-control-screen"><Volume2 size={32} /><strong>{state?.volume?.muted ? 'Muted' : Number.isFinite(state?.volume?.volume) ? `${Math.round(state.volume.volume)}%` : Number.isFinite(state?.volume?.brightness) ? `${Math.round(state.volume.brightness)}%` : 'Control mode'}</strong><p>Paired Mac · {Number.isFinite(state?.volume?.brightness) ? 'brightness' : 'system volume'}</p></div> : active && !previewError && !cameraPreviewPrivate ? <img src={previewUrl(`${active.revision}:${state?.preview_version || 'initial'}`)} alt="Actual host-rendered preview of the active Modulate program" width="240" height="135" onError={() => setPreviewError(true)} /> : <div className="mc-screen-empty"><Sparkles size={35} /><strong>{cameraPreviewPrivate ? 'Camera preview is private' : previewError ? 'Preview unavailable' : 'Ready for an idea.'}</strong><p>{cameraPreviewPrivate ? 'Allow browser camera preview in Permissions to see it here.' : previewError ? 'Your active program is retained.' : 'Your program will appear here.'}</p></div>}{agentRunning && <div className="mc-preview-processing"><Loader2 size={20} className="mc-spin" /><span>{state?.agent?.title || 'Processing your request'}</span></div>}</div><div className="mc-screen-bottom"><span className="mc-dot" /><span>PROGRAMMABLE BY YOU</span><span>▰ ▰ ▰</span></div></div></div><div className="mc-preview-footer"><span><span className="mc-dot" />{audioRunning ? 'Your Mac audio is playing through Modulate.' : 'Preview of your current app.'}</span></div></Card>
            {responseVisible && <Card className="mc-response"><div><Sparkles size={19} /><h2>Modulate replied</h2><Button quiet disabled={genericDisabled} onClick={async () => { if (await act('response', '/api/response/dismiss', { id: response.id })) setDismissedResponse(response.id); }}>Dismiss</Button></div><p aria-live="polite">{response.text}</p></Card>}
            {draft && <Card className="mc-draft"><div className="mc-card-heading"><h2>Review your spoken request</h2><Badge>{draft.editing ? 'Sending paused' : draftSeconds === 0 ? 'Sending…' : `Sending in ${draftSeconds ?? '—'}s`}</Badge></div><label className="mc-sr-only" htmlFor="mc-draft">Spoken request</label><textarea id="mc-draft" value={draftText} readOnly={!draft.editing} maxLength={2000} onChange={event => setDraftText(event.target.value)} /><div className="mc-draft-actions"><Button quiet disabled={genericDisabled} onClick={() => act('draft', '/api/draft', { job_id: draft.job_id, action: 'discard' })}>Discard</Button>{!draft.editing && <Button disabled={genericDisabled || draftSeconds === 0} onClick={() => act('draft', '/api/draft', { job_id: draft.job_id, action: 'pause' })}>Edit</Button>}<Button primary disabled={genericDisabled || !draftText.trim() || (!draft.editing && draftSeconds === 0)} onClick={() => act('draft', '/api/draft', { job_id: draft.job_id, action: 'send', text: draftText.trim() })}>Send now<ArrowUpRight size={15} /></Button></div></Card>}
            <Card className="mc-composer">{state?.clarification && <div className="mc-clarification"><span className="mc-eyebrow">{state.clarification.kind === 'recovery' ? 'LET’S GET THIS WORKING' : 'ONE QUICK QUESTION'}</span><p>{state.clarification.question}</p><span>Answer directly after the question. No “Hey Meta” needed.</span><Button quiet disabled={genericDisabled} onClick={() => act('cancel', '/api/cancel', {})}>Keep current app</Button></div>}<form onSubmit={sendRequest}><label htmlFor="mc-request"><Sparkles size={18} />{state?.clarification ? 'Your answer' : 'What should it become?'}</label><textarea id="mc-request" ref={requestRef} value={request} onChange={event => setRequest(event.target.value)} onKeyDown={event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); sendRequest(); } }} maxLength={4000} rows={3} placeholder={state?.clarification ? 'Reply here…' : 'Make an original kart racer. Use the joystick to steer and button A to boost…'} /><div className="mc-composer-bottom"><button type="button" className="mc-voice-help" onClick={() => setShowVoiceHelp(!showVoiceHelp)} aria-expanded={showVoiceHelp}><AudioLines size={18} />Device microphone</button><span className="mc-shortcut"><Command size={11} /> Enter</span><Button type="submit" primary disabled={!deviceConnected || agentRunning || Boolean(busy) || !request.trim()}>Send request<ArrowUpRight size={17} /></Button></div></form>{showVoiceHelp && <p className="mc-voice-instructions">Say “Hey Meta,” or hold both small screen buttons, then speak into the device microphone. Three seconds of silence finishes your request. You have another three seconds to choose Edit here before it sends. Answer follow-up questions directly within 20 seconds. Say “Hey Meta, cancel rebuild” to stop. This page does not record your browser microphone.</p>}<div className="mc-examples"><span>TRY</span><button onClick={() => chooseExample('Create an original kart racer')}>A kart racer<ArrowUpRight size={12} /></button><button onClick={() => chooseExample('Use the knob for my Mac volume')}>Mac volume<ArrowUpRight size={12} /></button><button onClick={() => chooseExample('Show my Mac camera with a fun visual twist')}>Camera remix<ArrowUpRight size={12} /></button></div></Card>
            <details className="mc-app-options"><summary>App options</summary><Button quiet icon={RotateCcw} disabled={genericDisabled || agentRunning || !active?.previous} onClick={() => act('rollback', '/api/rollback', {})}>Restore previous</Button><Button quiet icon={Code2} onClick={() => navigate('code')}>View code & checks</Button></details>
          </div></div>
        </>}

        {view === 'device' && <>
          {renderHardware()}
          <div className="mc-services-grid"><Card><div className="mc-card-heading"><h2>Your Mac</h2><Monitor size={20} /></div><Badge live={state?.paired}>{state?.paired ? 'Paired' : 'Not paired'}</Badge><p className="mc-service-description">{state?.paired ? 'Native controls run through your Mac companion.' : 'Modulate works on its own. Connect this Mac only for native computer controls.'}</p>{Number.isFinite(state?.volume?.volume) && <div className="mc-volume-readout"><span>System volume</span><strong>{state.volume.muted ? 'Muted' : `${state.volume.volume}%`}</strong><div><i style={{ width: `${Math.max(0, Math.min(100, state.volume.volume))}%` }} /></div></div>}<div className="mc-inline-actions">{state?.paired ? <Button danger quiet disabled={genericDisabled} onClick={() => act('revoke', '/api/revoke', {})}>Revoke Mac pairing</Button> : <Button icon={Link2} disabled={genericDisabled} onClick={() => standalone ? navigate('setup') : createDevicePairing()}>Connect this Mac</Button>}<Button quiet onClick={() => navigate('permissions')}>Permissions<ArrowRight size={14} /></Button></div></Card>
          <Card><div className="mc-card-heading"><h2>Voice & speaker</h2><AudioLines size={20} /></div><div className="mc-setting-row"><div><strong>Wake listening</strong><span>{state?.device?.telemetry?.voice?.message || human(state?.device?.telemetry?.voice?.state) || 'Awaiting microphone'}</span></div><Toggle label="Wake listening" checked={state?.wake} disabled={genericDisabled || !deviceConnected} onChange={enabled => act('wake', '/api/wake', { enabled })} /></div><p className="mc-service-description">{state?.speech?.provider === 'elevenlabs' ? 'ElevenLabs' : state?.speech?.provider || 'Voice'} · {human(speaker?.state) || 'Awaiting speaker'}{state?.speech?.error || speaker?.error ? ` · ${state?.speech?.error || speaker?.error}` : ''}</p><div className="mc-inline-actions"><Button icon={Volume2} disabled={genericDisabled || !speaker?.available} onClick={() => act('speaker', '/api/speaker', { action: 'test' })}>Test speaker</Button><Button quiet danger disabled={genericDisabled || !speaker} onClick={() => act('speaker', '/api/speaker', { action: 'stop' })}>Stop audio</Button></div></Card>
          <Card><div className="mc-card-heading"><h2>Live connections</h2><Radio size={20} /></div><div className="mc-connection-row"><Camera size={18} /><div><strong>Mac camera</strong><span>{state?.camera?.error || (cameraRunning ? 'Live · Mac → Pi' : 'Starts when requested')}</span></div>{cameraRunning && <Button quiet danger onClick={() => act('camera', '/api/camera/stop', {})} disabled={genericDisabled}>Stop</Button>}</div><div className="mc-connection-row"><Volume2 size={18} /><div><strong>Computer audio</strong><span>{state?.computer_audio?.error || (audioRunning ? 'Streaming to Pi speaker' : 'Starts when requested')}</span></div>{audioRunning && <Button quiet danger onClick={() => act('audio', '/api/audio/stop', {})} disabled={genericDisabled}>Stop</Button>}</div><div className="mc-connection-row"><MousePointer2 size={18} /><div><strong>Computer use</strong><span>{computer?.error || (computer?.enabled ? 'Access follows Mac pairing' : computer?.paused ? 'Access paused' : 'Waiting for permissions')}</span></div>{computer?.enabled ? <Button quiet danger disabled={genericDisabled} onClick={() => act('computer', '/api/computer', { action: 'revoke' })}>Pause</Button> : computer?.paused ? <Button quiet disabled={genericDisabled || !computer?.supported} onClick={() => act('computer', '/api/computer', { action: 'enable' })}>Resume</Button> : null}</div></Card></div>
        </>}

        {view === 'permissions' && <div className="mc-access-page">
          <p className="mc-access-intro">Choose what Modulate can use. Changes apply across voice and all connected browsers.</p>
          <Card className="mf-access-card">{PERMISSIONS.map(({ key, icon: Icon, title, detail }) => <div className="mf-access-row" key={key}><Icon size={20} /><div><strong>{title}</strong><p>{detail}</p></div><Toggle label={`Allow ${title.toLowerCase()}`} checked={permissions[key] === true} disabled={genericDisabled} onChange={enabled => togglePermission(key, enabled)} /></div>)}</Card>
          <details className="mc-permission-advanced"><summary>Mac permissions & privacy</summary><div className="mc-permission-details"><Card><div className="mc-card-heading"><h2>Mac system permissions</h2><Monitor size={20} /></div><p className="mc-service-description">Open System Settings → Privacy & Security on the paired Mac. Allow the Modulate companion where prompted.</p><div className="mc-permission-status"><div><span>Screen Recording</span><Badge live={computer?.permissions?.screen_recording === true}>{computer?.permissions?.screen_recording === true ? 'Granted' : computer?.permissions?.screen_recording === false ? 'Required' : 'Not checked'}</Badge></div><div><span>Accessibility</span><Badge live={computer?.permissions?.accessibility === true}>{computer?.permissions?.accessibility === true ? 'Granted' : computer?.permissions?.accessibility === false ? 'Required' : 'Not checked'}</Badge></div><div><span>Camera / audio recording</span><span className="mc-muted mc-small">macOS prompts when needed</span></div></div>{computer?.error && <p className="mc-inline-error">{computer.error}</p>}</Card><Card><div className="mc-card-heading"><h2>Your recent context</h2><Sparkles size={20} /></div><p className="mc-service-description">Modulate uses recent requests to understand refinements like “make it louder.” Computer-task details are kept separately and briefly.</p><div className="mc-memory-stat"><strong>{state?.memory?.turns ?? '—'}</strong><span>recent requests{state?.memory?.hours ? ` · up to ${state.memory.hours} hours` : ''}</span></div><Button quiet icon={RotateCcw} disabled={genericDisabled || agentRunning || !state?.memory?.turns} onClick={() => act('memory', '/api/context/clear', {})}>Forget recent context</Button></Card></div>
</details>
          <p className="mc-access-intro">Your Mac still asks for native permissions when needed. Provider keys stay on the server; this browser never receives them.</p>
        </div>}

        {view === 'library' && (authenticated ? <AppLibrary library={state?.library} disabled={genericDisabled} running={agentRunning} deviceConnected={deviceConnected} now={now} onAction={act} /> : <Card className="mc-empty"><Library size={28} /><strong>Connect to see your apps</strong><Button onClick={() => navigate('studio')}>Connect your device</Button></Card>)}

        {view === 'activity' && <><div className="mc-activity-overview"><Card><span className="mc-eyebrow">CURRENT STATUS</span><h2>{agentRunning ? state?.agent?.title || 'Working on your request' : state?.clarification ? 'Waiting for your answer' : authenticated ? 'Ready for your next idea' : 'Connect to see activity'}</h2><p>{state?.agent?.summary || 'The agent decides which tools and specialist skills to use for each request.'}</p>{agentRunning && <Button danger icon={Square} disabled={genericDisabled} onClick={() => act('cancel', '/api/cancel', {})}>Cancel request</Button>}</Card><Card><span className="mc-eyebrow">PROVIDER USAGE</span><div className="mc-usage-number">{Number.isFinite(budget?.charged_or_reserved_dollars) ? `$${budget.charged_or_reserved_dollars.toFixed(3)}` : '—'}<span>{Number.isFinite(budget?.limit_dollars) ? ` / $${budget.limit_dollars.toFixed(0)}` : ''}</span></div><p>Reserved or used · {state?.provider || 'provider unavailable'}</p>{Number.isFinite(budget?.charged_or_reserved_dollars) && <div className="mc-usage-track"><span style={{ width: `${Math.min(100, budget.charged_or_reserved_dollars / budget.limit_dollars * 100)}%` }} /></div>}</Card></div><Card className="mc-full-activity"><div className="mc-card-heading"><h2>Activity timeline</h2><span className="mc-muted mc-small">Most recent first</span></div>{renderEvents()}</Card></>}

        {view === 'code' && <Card className="mc-code-card"><div className="mc-code-heading"><div className="mc-segmented">{['active', 'candidate'].map(source => <button key={source} className={inspectSource === source ? 'is-selected' : ''} aria-pressed={inspectSource === source} disabled={!state?.[source]} onClick={() => setInspectSource(source)}>{human(source)}</button>)}</div><span className="mc-read-only"><ShieldCheck size={14} />Read only</span></div><h2>{selected?.title || selectedPackage?.title || 'No package to inspect'}</h2><p className="mc-code-revision">{selected?.revision || 'Create an experience to see its source, assets and checks.'}</p><div className="mc-code-tabs" role="tablist" aria-label="Package details">{[['code', 'Source'], ['assets', 'Assets'], ['checks', 'Checks']].map(([key, label]) => <button key={key} id={`mc-tab-${key}`} role="tab" aria-selected={inspectView === key} aria-controls="mc-code-content" className={inspectView === key ? 'is-selected' : ''} onClick={() => setInspectView(key)}>{label}</button>)}<Button quiet icon={copied ? Check : Copy} disabled={!selectedPackage} onClick={async () => { try { await navigator.clipboard.writeText(pretty(inspectContent)); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch (_) { setNotice({ type: 'error', text: 'Clipboard unavailable. Select the source text to copy it.' }); } }}>{copied ? 'Copied' : 'Copy'}</Button></div><pre id="mc-code-content" role="tabpanel" aria-labelledby={`mc-tab-${inspectView}`} tabIndex={0}><code>{pretty(inspectContent)}</code></pre><div className="mc-code-footer">Generated applications run in the isolated device runtime. These are the actual package and recorded checks.</div></Card>}

        <footer className="mc-footer"><div><img className="mc-footer-symbol" src={metaLogo.src || metaLogo} alt="" width={24} height={24} aria-hidden="true" /><span>Built with Meta AI</span>{authenticated && state?.model && <><span>·</span><span>{state.model}</span></>}</div><div>Connect. Create. Play.</div></footer>
      </main>
    </div>

    {pairing && <div className="mc-modal-backdrop"><section ref={pairingRef} className="mc-modal" role="dialog" aria-modal="true" aria-labelledby="mc-pairing-title"><button className="mc-modal-close" aria-label="Close pairing" onClick={() => setPairing(null)}><X size={20} /></button><span className="mc-section-icon"><Link2 size={25} /></span><h2 id="mc-pairing-title">Confirm on your Modulate</h2><p>Check that this code matches “Link this Mac?” on the device. Press small screen button A to allow, or B to decline.</p><output className="mc-physical-code">{dateMs(pairing.expires_at) <= now ? 'EXPIRED' : pairing.code}</output><p className="mc-small mc-muted">{Number.isFinite(dateMs(pairing.expires_at)) ? `Code expires at ${clock(pairing.expires_at)}` : 'One-time code · confirm on the device'}</p><Button primary disabled={Boolean(busy)} onClick={createDevicePairing}>Create a new code</Button></section></div>}
  </div>;
}
