'use client';

import React, { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  ArrowRight,
  Check,
  ChevronRight,
  Code2,
  Cpu,
  Eye,
  FlaskConical,
  Gamepad2,
  LayoutDashboard,
  Library,
  Loader2,
  MessageCircle,
  Mic,
  Monitor,
  Plus,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Star,
  Sun,
  Trash2,
  Undo2,
  Volume2,
  Wrench,
  X,
} from 'lucide-react';
import { Badge, Brand, Button } from '../ui';
import VirtualDevice from './VirtualDevice';
import {
  checkApp,
  COMPUTER,
  contract,
  freshWorkspace,
  hardwareReport,
  hasConflict,
  libraryList,
  MODULES,
  readyModules,
  restoreWorkspace,
  SCENES,
  STORAGE_KEY,
} from './model';
import '../connect.css';
import './demo.css';

const NAV = [
  ['studio', LayoutDashboard, 'Studio'],
  ['library', Library, 'App library'],
  ['device', Cpu, 'Device'],
];
const ROLE_ICONS = {
  orchestrator: Sparkles,
  coder: Code2,
  verifier: ShieldCheck,
  reviewer: Eye,
  bench: Wrench,
};
const ROLE_NAMES = {
  orchestrator: 'Orchestrator',
  coder: 'Coder subagent',
  verifier: 'Independent checks',
  reviewer: 'Reviewer subagent',
  bench: 'Hardware bench',
};
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
// Trusted repair workflow for a factory-address Qwiic Button; the model only starts it.
const REPAIR_STEPS = {
  awaiting_isolation: {
    text: 'Shut down and unplug the Pi, disconnect the Qwiic chain, and connect only the new button to the PiTFT’s QT port. Boot, then confirm.',
    confirm: 'Isolated button ready',
  },
  awaiting_power_cycle: {
    text: 'Address written. Shut down and unplug with the button still isolated, then power back on and confirm.',
    confirm: 'Button power cycled',
  },
  awaiting_reconnect: {
    text: 'Verified at 0x6D. Shut down, reconnect the original chain plus the new button, boot, and confirm.',
    confirm: 'Modules reconnected',
  },
};

export default function Demo() {
  const [workspace, setWorkspace] = useState(freshWorkspace);
  const [ready, setReady] = useState(false);
  const [storageAvailable, setStorageAvailable] = useState(true);
  const [view, setView] = useState('studio');
  const [request, setRequest] = useState('');
  const [channel, setChannel] = useState('device');
  const [notice, setNotice] = useState('');
  const [build, setBuild] = useState(null);
  const [trace, setTrace] = useState(null);
  const [lastInference, setLastInference] = useState(null);
  const [candidate, setCandidate] = useState(null);
  const [previousId, setPreviousId] = useState(null);
  const [say, setSay] = useState('');
  const [question, setQuestion] = useState('');
  const [conversation, setConversation] = useState([]);
  const [menu, setMenu] = useState({ open: false, selected: 0 });
  const [tab, setTab] = useState('all');
  const [bench, setBench] = useState(null);
  const [rename, setRename] = useState(null);
  const [showReset, setShowReset] = useState(false);
  const [purge, setPurge] = useState(null);
  const generation = useRef(null);
  const benchRun = useRef(0);
  const main = useRef(null);
  const modules = readyModules(workspace);
  const active = workspace.apps.find((app) => app.id === workspace.activeId);
  const entries = libraryList(workspace.apps);
  const busy = Boolean(build) || bench?.phase === 'running';
  const conflict = hasConflict(workspace);
  const imuState = !workspace.modules.includes('imu') ? 'detached' : workspace.hardware.imuDriver;
  const paired = workspace.modules.includes(COMPUTER);

  useEffect(() => {
    // The legacy Connect layout restores its title on unmount during client navigation.
    document.title = 'Modulate Playground — Try a virtual device';
    try {
      setWorkspace(restoreWorkspace(localStorage.getItem(STORAGE_KEY)));
    } catch {
      setStorageAvailable(false);
    }
    setReady(true);
  }, []);
  useEffect(() => {
    if (!ready) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(workspace));
    } catch {
      setStorageAvailable(false);
    }
  }, [workspace, ready]);
  useEffect(() => () => generation.current?.abort(), []);
  useEffect(() => {
    if (!say) return;
    const timer = setTimeout(() => setSay(''), 9000);
    return () => clearTimeout(timer);
  }, [say]);

  const update = (change) => setWorkspace((current) => ({ ...current, ...change(current) }));
  const remember = (role, text, kind = '') =>
    setConversation((c) => [...c.slice(-7), { role, text, kind, channel }]);
  const activate = (app) => {
    setPreviousId(workspace.activeId);
    setWorkspace((current) => ({
      ...current,
      apps: current.apps.some((a) => a.id === app.id)
        ? current.apps.map((a) => (a.id === app.id ? { ...a, trashed: false } : a))
        : [...current.apps.slice(-23), { ...app, favorite: false, trashed: false }],
      activeId: app.id,
    }));
    setCandidate(null);
    setBuild(null);
    setMenu((m) => ({ ...m, open: false }));
    if (app.trace) {
      setTrace(app.trace);
      setLastInference(app.inference || null);
    }
    setNotice(
      app.kind === 'controls'
        ? `${app.title} is active. Turn the knob — it runs locally.`
        : `${app.title} passed the checks and is ready. Press Play app.`,
    );
  };
  const reject = (message) => {
    setCandidate(null);
    setBuild(null);
    setNotice(/previous app is kept/.test(message) ? message : `${message} Your previous app is kept.`);
  };
  const cancel = () => {
    generation.current?.abort();
    generation.current = null;
    setCandidate(null);
    setBuild(null);
    setNotice(
      'Cancelled. Your previous app is kept. An inference already sent may still count toward the allowance.',
    );
  };
  const navigate = (next) => {
    setView(next);
    setRename(null);
    main.current?.scrollTo?.({ top: 0 });
  };
  const toggleModule = (id) => {
    if (busy) return;
    update((current) => ({
      modules: current.modules.includes(id)
        ? current.modules.filter((m) => m !== id)
        : [...current.modules, id],
    }));
  };
  const loadApp = (app) => {
    if (busy) return;
    const error = checkApp(app, modules);
    if (error) {
      setNotice(error);
      return;
    }
    setMenu((m) => ({ ...m, open: false }));
    if (app.id !== workspace.activeId) {
      setCandidate(app);
      setBuild({ phase: 'Checking saved app on your virtual device…' });
    }
    navigate('studio');
  };
  const setFlag = (id, flags) =>
    update((current) => ({
      apps: current.apps.map((a) => (a.id === id ? { ...a, ...flags } : a)),
    }));
  // Favorites sort first, so keep the menu selection on the app that moved.
  const favorite = (id, value) => {
    setFlag(id, { favorite: value });
    const next = libraryList(
      workspace.apps.map((a) => (a.id === id ? { ...a, favorite: value } : a)),
    );
    const index = next.findIndex((a) => a.id === id);
    if (index >= 0) setMenu((m) => ({ ...m, selected: index }));
  };
  const trash = (app) => {
    if (app.id === workspace.activeId) {
      setNotice(`${app.title} is on your device. Open another app before moving it to Trash.`);
      return false;
    }
    setFlag(app.id, { trashed: true, favorite: false });
    return true;
  };
  const applyLibrary = ({ op, entry, control }) => {
    const app = workspace.apps.find((a) => a.id === entry);
    if (op === 'open') setMenu({ open: true, selected: 0 });
    if (op === 'close') setMenu((m) => ({ ...m, open: false }));
    if (op === 'favorite' || op === 'unfavorite') favorite(entry, op === 'favorite');
    if (op === 'trash' && app) trash(app);
    if (op === 'restore') setFlag(entry, { trashed: false });
    if (op === 'launch' && app) loadApp(app);
    if (op === 'scroll_with') {
      update(() => ({ libraryControl: control }));
      setMenu((m) => ({ ...m, open: true }));
    }
  };
  const onLibrary = (event) => {
    if (!entries.length) return;
    const selected = Math.min(menu.selected, entries.length - 1);
    if (event.type === 'move')
      setMenu((m) => ({
        ...m,
        selected: Math.max(0, Math.min(entries.length - 1, m.selected + event.delta)),
      }));
    if (event.type === 'launch') loadApp(entries[selected]);
    if (event.type === 'favorite') favorite(entries[selected].id, !entries[selected].favorite);
  };
  const log = (line) => setBench((b) => b && { ...b, log: [...b.log, line] });
  const runBench = async ({ op }) => {
    const run = ++benchRun.current;
    const live = () => benchRun.current === run;
    if (op === 'inspect') {
      const report = hardwareReport(workspace);
      setBench({
        op,
        phase: 'done',
        log: report.bus.map((d) => `${d.address} · ${d.device} — ${d.status}`),
      });
      return;
    }
    if (op === 'install_driver') {
      setBench({ op, phase: 'running', log: [] });
      for (const [ms, line] of [
        [700, 'Chip identity at 0x6A: WHO_AM_I = 0x6A → LSM6DS3TR-C ✓'],
        [1100, 'Pinned driver pack fetched · SHA-256 verified ✓'],
        [900, 'Driver loaded · samples ax −0.17  ay −0.27  az 9.97 m/s² ✓'],
        [400, 'Committed. The previous setup would be restored on failure.'],
      ]) {
        await wait(ms);
        if (!live()) return;
        log(line);
      }
      update((current) => ({ hardware: { ...current.hardware, imuDriver: 'ready' } }));
      setBench((b) => b && { ...b, phase: 'done' });
      setSay('Motion sensor driver installed and verified. Tilt is ready.');
      return;
    }
    if (op === 'begin_button_repair')
      setBench({
        op,
        phase: 'awaiting_isolation',
        log: ['0x6F answers for two boards: a new Qwiic Button kept its factory address.'],
      });
  };
  const confirmRepair = async () => {
    const run = benchRun.current;
    const live = () => benchRun.current === run;
    const phase = bench.phase;
    setBench((b) => ({ ...b, phase: 'running' }));
    if (phase === 'awaiting_isolation') {
      await wait(900);
      if (!live()) return;
      log('Isolated board: device ID 0x5D, firmware 259 ✓ (supported)');
      await wait(900);
      if (!live()) return;
      log('Wrote unused address 0x6D to register 0x1F ✓');
      setBench((b) => ({ ...b, phase: 'awaiting_power_cycle' }));
    } else if (phase === 'awaiting_power_cycle') {
      await wait(900);
      if (!live()) return;
      log('After power cycle the button answers at 0x6D ✓');
      setBench((b) => ({ ...b, phase: 'awaiting_reconnect' }));
    } else if (phase === 'awaiting_reconnect') {
      await wait(900);
      if (!live()) return;
      update((current) => ({
        hardware: { ...current.hardware, extraButton: { address: '0x6d' } },
      }));
      log('Scan: 0x20 0x36 0x6A 0x6D 0x6E 0x6F — conflict resolved ✓');
      log('The runtime still exposes buttons A and B; the third button is ready for setup.');
      setBench((b) => ({ ...b, phase: 'done' }));
      setSay('All three buttons now have their own address.');
    }
  };
  const send = async (event, text = request, via = channel) => {
    event?.preventDefault?.();
    const prompt = text.trim();
    if (busy || !prompt) return;
    if (!workspace.modules.includes('display')) {
      setNotice('Attach a display before asking Modulate for something.');
      return;
    }
    const controller = new AbortController();
    generation.current = controller;
    const history = conversation.map(({ role, text: t }) => ({ role, text: t }));
    setNotice('');
    setTrace([]);
    setQuestion('');
    setRequest('');
    remember('user', prompt);
    setBuild({ phase: 'Connecting to Meta…' });
    main.current?.scrollTo?.({ top: 0, behavior: 'smooth' });
    try {
      const sessionResponse = await fetch('/api/demo', { signal: controller.signal });
      const session = await sessionResponse.json();
      if (!sessionResponse.ok) throw Error(session.error);
      const response = await fetch('/api/demo', {
        method: 'POST',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-Demo-CSRF': session.csrf },
        body: JSON.stringify({
          prompt,
          channel: via,
          modules,
          previous: active ? contract(active) : null,
          library: {
            open: menu.open,
            entries: workspace.apps.map((a) => ({
              id: a.id,
              title: a.title,
              kind: a.kind || 'app',
              favorite: a.favorite,
              trashed: a.trashed,
            })),
          },
          computer: paired ? workspace.computer : null,
          hardware: hardwareReport(workspace, bench?.op === 'begin_button_repair' ? bench.phase : null),
          history,
        }),
      });
      if (!response.ok) {
        const body = await response.json();
        throw Error(body.error || 'Generation unavailable.');
      }
      const reader = response.body.getReader(),
        decoder = new TextDecoder();
      let buffer = '',
        result = null;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        if (buffer.length > 100000) throw Error('The generation response was too large.');
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          const message = JSON.parse(line);
          if (generation.current !== controller) return;
          if (message.type === 'phase') setBuild({ phase: message.phase });
          if (message.type === 'trace')
            setTrace((t) => {
              const next = [...(t || [])];
              if (Number.isInteger(message.index)) next[message.index] = message.step;
              else next.push(message.step);
              return next;
            });
          if (message.type === 'error') throw Error(message.error);
          if (message.type === 'result') result = message;
        }
      }
      if (generation.current !== controller) return;
      if (!result) throw Error('The request ended without a verified result.');
      const kind = result.kind || 'app';
      setTrace(result.trace || []);
      setLastInference(result.inference || null);
      if (result.say) {
        setSay(result.say);
        remember('assistant', kind === 'ask' ? result.question : result.say, kind);
      }
      if (kind === 'app' || kind === 'controls') {
        // Revisions of the same idea get a visible version instead of duplicate names.
        const versions = workspace.apps.filter(
          (a) =>
            a.id !== result.revision &&
            (a.title === result.app.title || a.title.startsWith(`${result.app.title} · v`)),
        ).length;
        const app = {
          ...result.app,
          title: versions ? `${result.app.title} · v${versions + 1}` : result.app.title,
          id: result.revision,
          checks: result.checks,
          review: result.review,
          inference: result.inference,
          trace: result.trace,
        };
        const error = checkApp(app, modules);
        if (error) throw Error(error);
        setBuild({ phase: 'Waiting for virtual device acknowledgement…' });
        setCandidate(app);
        return;
      }
      setBuild(null);
      if (kind === 'ask') setQuestion(result.question);
      if (kind === 'library') applyLibrary(result.library);
      if (kind === 'debug') runBench(result.debug);
    } catch (error) {
      if (generation.current === controller)
        reject(error.name === 'AbortError' ? 'Cancelled.' : error.message);
    }
  };
  const rollback = () => {
    const previous = workspace.apps.find((app) => app.id === previousId);
    if (previous) loadApp(previous);
  };
  const componentTray = (
    <div className="md-module-list">
      {MODULES.map((module) => {
        const connected = workspace.modules.includes(module.id);
        const missingDriver = module.id === 'imu' && connected && imuState === 'missing';
        return (
          <button
            className={`md-module ${connected ? 'is-attached' : ''} ${missingDriver ? 'is-warning' : ''}`}
            key={module.id}
            type="button"
            aria-pressed={connected}
            aria-label={`${connected ? 'Remove' : 'Attach'} ${module.name.toLowerCase()}`}
            disabled={busy || !ready}
            onClick={() => toggleModule(module.id)}
          >
            <span className={`md-module-symbol md-symbol-${module.id}`}>{module.symbol}</span>
            <span className="md-module-copy">
              <strong>{module.name}</strong>
              <small>{missingDriver ? 'Driver missing — ask Modulate' : module.detail}</small>
            </span>
            <span className="md-module-state">
              {connected ? <Check size={15} /> : <Plus size={15} />}
            </span>
          </button>
        );
      })}
    </div>
  );
  const faultButtons = (
    <div className="md-hw-actions">
      <Button
        quiet
        disabled={busy || imuState === 'missing'}
        onClick={() => {
          update((current) => ({
            modules: [...new Set([...current.modules, 'imu'])],
            hardware: { ...current.hardware, imuDriver: 'missing' },
          }));
          setNotice('Motion sensor plugged in without its driver. Tilt is unavailable.');
        }}
      >
        Plug in IMU without its driver
      </Button>
      <Button
        quiet
        disabled={busy || Boolean(workspace.hardware.extraButton)}
        onClick={() => {
          update((current) => ({
            modules: [...new Set([...current.modules, 'buttons'])],
            hardware: { ...current.hardware, extraButton: { address: '0x6f' } },
          }));
          setNotice('A third Qwiic Button joined the bus at its factory address, 0x6F.');
        }}
      >
        Add a third button (factory 0x6F)
      </Button>
      <Button
        quiet
        icon={RotateCcw}
        disabled={busy}
        onClick={() => {
          benchRun.current++;
          setBench(null);
          update(() => ({ hardware: { imuDriver: 'ready', extraButton: null } }));
        }}
      >
        Reset bench
      </Button>
    </div>
  );
  const benchPanel = bench && (
    <section className="md-bench-flow" aria-label="Hardware debugger workflow">
      <div className="md-panel-heading">
        <div>
          <span className="md-eyebrow">HARDWARE DEBUGGER · SIMULATED BUS</span>
          <h2>
            {bench.op === 'install_driver'
              ? 'Installing a verified driver'
              : bench.op === 'begin_button_repair'
                ? 'Guided button re-address'
                : 'Bus inspection'}
          </h2>
        </div>
        <Button quiet aria-label="Close workflow" icon={X} onClick={() => setBench(null)} />
      </div>
      <ol>
        {bench.log.map((line, i) => (
          <li key={i}>{line}</li>
        ))}
        {bench.phase === 'running' && (
          <li className="is-running">
            <Loader2 className="md-spin" size={13} /> Working…
          </li>
        )}
      </ol>
      {REPAIR_STEPS[bench.phase] && (
        <div className="md-bench-step">
          <p>{REPAIR_STEPS[bench.phase].text}</p>
          <Button primary onClick={confirmRepair}>
            {REPAIR_STEPS[bench.phase].confirm}
          </Button>
        </div>
      )}
      <p className="md-bench-note">
        Simulated hardware, real agent decision. On the physical Pi the same trusted installer
        verified the LSM6DS3TR-C in 7.6 s; physical steps always need a person.
      </p>
    </section>
  );
  const traceCard = trace && (
    <section className="md-trace" aria-label="Agent trace">
      <div className="md-panel-heading">
        <div>
          <span className="md-eyebrow">AGENT TRACE · LIVE</span>
          <h2>What Muse Spark did</h2>
        </div>
        {lastInference && !build && (
          <span className="md-pi-chip">
            {lastInference.model} · {lastInference.calls?.length} calls · {lastInference.seconds}s
          </span>
        )}
      </div>
      <ol>
        {trace.map((step, i) => {
          const Icon = ROLE_ICONS[step.role] || Sparkles;
          return (
            <li key={i} className={`is-${step.status}`}>
              <Icon size={15} />
              <div>
                <strong>
                  {ROLE_NAMES[step.role] || step.role} · {step.title}
                </strong>
                {step.detail && <span>{step.detail}</span>}
              </div>
              <small>{step.at}s</small>
            </li>
          );
        })}
        {build && (
          <li className="is-running">
            <Loader2 className="md-spin" size={15} />
            <div>
              <strong>{build.phase}</strong>
            </div>
          </li>
        )}
      </ol>
    </section>
  );

  return (
    <div className="mc-app md-app">
      <a href="#demo-main" className="mc-skip">
        Skip to playground
      </a>
      <aside className="md-sidebar">
        <Link href="/connect" aria-label="Modulate home">
          <Brand />
        </Link>
        <div className="md-workspace">
          <div className="md-workspace-icon">
            <FlaskConical size={21} />
          </div>
          <div>
            <strong>Your playground</strong>
            <span>No hardware required</span>
          </div>
        </div>
        <span className="mc-nav-label">WORKSPACE</span>
        <nav aria-label="Demo workspace">
          {NAV.map(([id, Icon, title]) => (
            <button
              type="button"
              key={id}
              className={view === id ? 'is-selected' : ''}
              aria-current={view === id ? 'page' : undefined}
              onClick={() => navigate(id)}
            >
              <Icon size={18} />
              <span>{title}</span>
              {id === 'library' && <small>{entries.length}</small>}
            </button>
          ))}
        </nav>
        <div className="md-sidebar-bottom">
          <span className="md-local-dot" />
          {storageAvailable ? 'Saved in this browser' : 'Session only · storage unavailable'}
          <p>
            Your own apps. Your own setup.
            <br />
            Come back and keep tinkering.
          </p>
          <Link href="/connect">
            Connect real hardware
            <ArrowRight size={14} />
          </Link>
        </div>
      </aside>
      <div className="md-shell" ref={main}>
        <header className="md-topbar">
          <span>
            <FlaskConical size={15} />
            ONLINE DEMO
          </span>
          <span className="md-topbar-detail">Real Meta inference · virtual hardware</span>
          <Link href="/connect">
            Exit demo
            <X size={15} />
          </Link>
        </header>
        <main id="demo-main" className="md-main" tabIndex={-1}>
          <div className="md-heading">
            <div>
              <span className="md-eyebrow">THE MODULATE PLAYGROUND</span>
              <h1>
                {view === 'studio'
                  ? 'A device that programs itself.'
                  : view === 'library'
                    ? 'Everything you made, kept.'
                    : 'Build your little machine.'}
              </h1>
              <p>
                {view === 'studio'
                  ? 'Plug in parts. Say what it should become. Muse Spark writes it, checks it and installs it.'
                  : view === 'library'
                    ? 'Favorite, trash or restore apps — or open the library on the device and scroll with the knob.'
                    : 'Attach or remove parts, then break the hardware on purpose and let Modulate debug it.'}
              </p>
            </div>
            <Badge>Live Meta AI</Badge>
          </div>
          <div className="md-disclosure">
            <FlaskConical size={16} />
            <p>
              Real Meta inference. Virtual hardware.{' '}
              <span>
                Your request goes to Meta Muse Spark (orchestrator, coder and reviewer). Generated
                apps run sandboxed in this tab. The Pi parts, I²C bus and paired Mac are
                simulated; your camera, if you allow it, never leaves this tab.
              </span>
            </p>
          </div>
          {!ready && <p role="status">Opening your playground…</p>}
          {notice && (
            <div className="md-notice" role="status">
              <span>{notice}</span>
              <button type="button" aria-label="Dismiss demo message" onClick={() => setNotice('')}>
                <X size={16} />
              </button>
            </div>
          )}
          {build && (
            <div className="md-build" role="status">
              <div>
                <Loader2 className="md-spin" size={18} />
                <strong>{build.phase}</strong>
                <Button quiet onClick={cancel}>
                  Cancel
                </Button>
              </div>
              <p>
                Orchestrate → write → independent checks → review → device acknowledgement. Your
                current app is kept until activation.
              </p>
            </div>
          )}
          {view === 'studio' && (
            <>
              <div className="md-studio-grid">
                <section className="md-bench" aria-labelledby="bench-title">
                  <div className="md-panel-heading">
                    <div>
                      <span className="md-eyebrow">ON YOUR DEVICE</span>
                      <h2 id="bench-title">
                        {menu.open ? 'App library' : active?.title || 'Your next idea'}
                      </h2>
                    </div>
                    <span className="md-pi-chip">
                      <Cpu size={14} />
                      Raspberry Pi
                    </span>
                  </div>
                  <VirtualDevice
                    app={active}
                    candidate={candidate}
                    modules={modules}
                    busy={busy || !ready}
                    onReady={activate}
                    onReject={reject}
                    computer={paired ? workspace.computer : null}
                    onComputer={(levels) => update(() => ({ computer: levels }))}
                    library={
                      menu.open
                        ? {
                            open: true,
                            entries,
                            selected: Math.min(menu.selected, Math.max(0, entries.length - 1)),
                            control: workspace.libraryControl,
                          }
                        : null
                    }
                    onLibrary={onLibrary}
                    imuState={imuState}
                    conflict={conflict}
                    say={say}
                  />
                  <div className="md-bench-bottom">
                    <span>
                      <i />
                      {workspace.modules.filter((m) => m !== COMPUTER).length} modules attached
                    </span>
                    <span className="md-bench-actions">
                      <Button
                        quiet
                        icon={Library}
                        disabled={busy}
                        onClick={() => setMenu((m) => ({ open: !m.open, selected: 0 }))}
                      >
                        {menu.open ? 'Close library' : 'Library on device'}
                      </Button>
                      <Button
                        quiet
                        icon={RotateCcw}
                        disabled={!previousId || busy}
                        onClick={rollback}
                      >
                        Restore previous app
                      </Button>
                    </span>
                  </div>
                </section>
                <div className="md-side">
                  <section className="md-parts" aria-labelledby="parts-title">
                    <div className="md-panel-heading">
                      <div>
                        <span className="md-eyebrow">MAKE IT MODULAR</span>
                        <h2 id="parts-title">Your components</h2>
                      </div>
                      <Cpu size={19} />
                    </div>
                    {componentTray}
                    <div className="md-tip">
                      <Sparkles size={16} />
                      <p>
                        Unplug a part mid-game, then ask to update the controls.
                        <br />
                        <strong>Meta writes for what’s attached.</strong>
                      </p>
                    </div>
                    <details className="md-faults">
                      <summary>
                        <Wrench size={13} /> Simulate a hardware fault
                      </summary>
                      {faultButtons}
                    </details>
                  </section>
                  <section className="md-computer" aria-label="Paired computer">
                    <div className="md-panel-heading">
                      <div>
                        <span className="md-eyebrow">PAIRED COMPUTER · VIRTUAL</span>
                        <h2>{paired ? 'Your Mac' : 'Not paired'}</h2>
                      </div>
                      <Button quiet disabled={busy} onClick={() => toggleModule(COMPUTER)}>
                        {paired ? 'Unpair' : 'Pair'}
                      </Button>
                    </div>
                    <div
                      className={`md-mac ${paired ? '' : 'is-off'}`}
                      style={{ '--mac-dim': (100 - workspace.computer.brightness) / 115 }}
                      aria-label={`Virtual Mac screen at ${workspace.computer.brightness}% brightness`}
                      role="img"
                    >
                      <div className="md-mac-screen">
                        <div className="md-mac-window">
                          <i />
                          <i />
                          <i />
                        </div>
                        <span className="md-mac-shade" />
                      </div>
                      <div className="md-mac-stand" />
                    </div>
                    <div className="md-levels">
                      <span>
                        <Sun size={14} /> {workspace.computer.brightness}%
                      </span>
                      <span>
                        <Volume2 size={14} /> {workspace.computer.volume}%
                      </span>
                    </div>
                    <p className="md-computer-note">
                      Stands in for your Mac. On real hardware the knob changes macOS brightness and
                      volume through a paired, revocable bridge.
                    </p>
                  </section>
                  {benchPanel}
                </div>
              </div>
              <section className="md-composer">
                <div className="md-composer-intro">
                  <span className="md-spark">
                    <Sparkles size={23} />
                  </span>
                  <div>
                    <h2>Say what it should become.</h2>
                    <p>
                      Type what you’d say to the device, or send it as a Muse message. Follow the
                      video’s scenes in order, or invent your own.
                    </p>
                  </div>
                  <span className="md-example-tag">LIVE · MUSE SPARK</span>
                </div>
                <div className="md-channels" role="tablist" aria-label="Request channel">
                  {[
                    ['device', Mic, 'Talk to the device', 'Typed in place of “Hey Meta…”'],
                    ['muse', MessageCircle, 'Message from Muse', 'Same agent, via the connector'],
                  ].map(([id, Icon, label, hint]) => (
                    <button
                      key={id}
                      type="button"
                      role="tab"
                      aria-selected={channel === id}
                      className={channel === id ? 'is-selected' : ''}
                      onClick={() => setChannel(id)}
                    >
                      <Icon size={15} />
                      <span>
                        <strong>{label}</strong>
                        <small>{hint}</small>
                      </span>
                    </button>
                  ))}
                </div>
                {conversation.length > 0 && (
                  <ol className="md-conversation" aria-label="Conversation">
                    {conversation.map((line, i) => (
                      <li key={i} className={`is-${line.role} is-${line.kind || 'note'}`}>
                        <strong>
                          {line.role === 'user'
                            ? line.channel === 'muse'
                              ? 'You · Muse'
                              : 'You'
                            : 'Modulate'}
                        </strong>
                        {line.kind === 'decline' && <ShieldAlert size={13} />}
                        <span>{line.text}</span>
                      </li>
                    ))}
                  </ol>
                )}
                {question && (
                  <p className="md-question" role="status">
                    Modulate asked: <strong>{question}</strong>
                  </p>
                )}
                <form onSubmit={send} className={channel === 'muse' ? 'is-muse' : ''}>
                  <label className="mc-sr-only" htmlFor="demo-request">
                    Demo request
                  </label>
                  <input
                    id="demo-request"
                    value={request}
                    maxLength={1200}
                    disabled={busy || !ready}
                    onChange={(e) => setRequest(e.target.value)}
                    placeholder={
                      question
                        ? 'Answer Modulate…'
                        : channel === 'muse'
                          ? 'Message Modulate from Muse…'
                          : 'Hey Meta, make a little racing game…'
                    }
                  />
                  <Button primary type="submit" disabled={busy || !ready || !request.trim()}>
                    {busy ? 'Working…' : 'Send'}
                    <ArrowRight size={16} />
                  </Button>
                </form>
                <div className="md-suggestions" aria-label="Video scenes">
                  {SCENES.map(([label, prompt, via], i) => (
                    <button
                      type="button"
                      key={label}
                      disabled={busy}
                      onClick={() => {
                        setRequest(prompt);
                        setChannel(via);
                      }}
                    >
                      <b>{i + 1}</b>
                      {label}
                      {via === 'muse' && <MessageCircle size={11} />}
                    </button>
                  ))}
                </div>
                <p className="md-composer-note">
                  Scene 2: unplug the joystick first. Scene 3: simulate a hardware fault first. Each browser gets a small daily allowance of live requests; saved apps,
                  knob mappings and the library always work.
                </p>
              </section>
              {traceCard}
              {active && (
                <details className="md-evidence">
                  <summary>
                    {active.kind === 'controls' ? 'Mapping & checks' : 'Code & checks'} ·{' '}
                    {active.inference?.model} · {active.inference?.calls?.length} live calls
                  </summary>
                  <p>{active.review}</p>
                  <p>
                    {active.kind === 'controls'
                      ? 'Declarative bindings, checked by the trusted verifier.'
                      : `${active.checks?.frames} server frames checked, plus browser verification.`}{' '}
                    {active.inference?.channel === 'muse' ? 'Muse message' : 'Typed'} input ·{' '}
                    {active.inference?.seconds}s · Revision: <code>{active.id}</code>
                  </p>
                  <ul>
                    {active.inference?.calls?.map((call, i) => (
                      <li key={i}>
                        {call.role || 'call'} · {call.model} · {call.usage.prompt_tokens} input /{' '}
                        {call.usage.completion_tokens} output tokens · response{' '}
                        <code>{call.responseId || 'ID unavailable'}</code>
                      </li>
                    ))}
                  </ul>
                  <pre>
                    <code>
                      {active.kind === 'controls'
                        ? JSON.stringify(active.bindings, null, 2)
                        : active.code}
                    </code>
                  </pre>
                </details>
              )}
            </>
          )}
          {view === 'library' && (
            <>
              <div className="md-tabs" role="tablist" aria-label="Library filter">
                {[
                  ['all', 'All'],
                  ['favorites', 'Favorites'],
                  ['trash', 'Trash'],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    aria-selected={tab === id}
                    className={tab === id ? 'is-selected' : ''}
                    onClick={() => setTab(id)}
                  >
                    {label}
                    <small>
                      {id === 'trash'
                        ? workspace.apps.filter((a) => a.trashed).length
                        : id === 'favorites'
                          ? entries.filter((a) => a.favorite).length
                          : entries.length}
                    </small>
                  </button>
                ))}
              </div>
              <section className="md-library" aria-label="Your demo apps">
                {(tab === 'trash'
                  ? workspace.apps.filter((a) => a.trashed)
                  : tab === 'favorites'
                    ? entries.filter((a) => a.favorite)
                    : entries
                ).map((app) => {
                  const selected = app.id === workspace.activeId;
                  return (
                    <article key={app.id} className="md-app-card">
                      <div
                        className={`md-app-art ${app.kind === 'controls' ? 'md-art-controls' : 'md-art-orbit'}`}
                        aria-hidden="true"
                      >
                        <span>{app.kind === 'controls' ? '◉' : '✦'}</span>
                        <i />
                        <b>✧</b>
                        <small>
                          {app.kind === 'controls' ? 'META CONTROL MAPPING' : 'META GENERATED APP'}
                        </small>
                      </div>
                      <div className="md-app-card-body">
                        {rename?.id === app.id ? (
                          <form
                            onSubmit={(e) => {
                              e.preventDefault();
                              if (rename.title.trim()) {
                                setFlag(app.id, { title: rename.title.trim() });
                                setRename(null);
                              }
                            }}
                          >
                            <label className="mc-sr-only" htmlFor="demo-app-name">
                              App name
                            </label>
                            <input
                              id="demo-app-name"
                              autoFocus
                              maxLength={60}
                              value={rename.title}
                              onChange={(e) => setRename({ ...rename, title: e.target.value })}
                            />
                            <Button type="submit">Save</Button>
                            <Button type="button" quiet onClick={() => setRename(null)}>
                              Cancel
                            </Button>
                          </form>
                        ) : (
                          <>
                            <h2>
                              {app.favorite && <Star size={15} className="md-star" />}
                              {app.title}
                            </h2>
                            <p>{app.description}</p>
                          </>
                        )}
                        <div className="md-app-card-meta">
                          <span>{app.inference?.calls?.length || 0} Meta calls · checked</span>
                          <span>{selected ? 'On device' : app.trashed ? 'In Trash' : 'Saved'}</span>
                        </div>
                        <div className="md-library-actions">
                          {app.trashed ? (
                            <>
                              <Button
                                icon={Undo2}
                                disabled={busy}
                                onClick={() => setFlag(app.id, { trashed: false })}
                              >
                                Restore
                              </Button>
                              {purge === app.id ? (
                                <Button
                                  danger
                                  onClick={() => {
                                    update((w) => ({ apps: w.apps.filter((a) => a.id !== app.id) }));
                                    if (previousId === app.id) setPreviousId(null);
                                    setPurge(null);
                                    setNotice(`${app.title} deleted from this browser.`);
                                  }}
                                >
                                  Confirm delete
                                </Button>
                              ) : (
                                <Button quiet icon={Trash2} onClick={() => setPurge(app.id)}>
                                  Delete forever
                                </Button>
                              )}
                            </>
                          ) : (
                            <>
                              <Button
                                primary={selected}
                                disabled={busy}
                                icon={Gamepad2}
                                onClick={() => loadApp(app)}
                              >
                                {selected ? 'Back to app' : 'Open app'}
                              </Button>
                              <Button
                                quiet
                                icon={Star}
                                aria-label={`${app.favorite ? 'Unfavorite' : 'Favorite'} ${app.title}`}
                                aria-pressed={app.favorite}
                                onClick={() => favorite(app.id, !app.favorite)}
                              />
                              <Button
                                quiet
                                disabled={busy}
                                onClick={() => setRename({ id: app.id, title: app.title })}
                              >
                                Rename
                              </Button>
                              <Button
                                quiet
                                icon={Trash2}
                                aria-label={`Move ${app.title} to Trash`}
                                disabled={selected || busy}
                                onClick={() => {
                                  if (trash(app)) setNotice(`${app.title} moved to Trash.`);
                                }}
                              />
                            </>
                          )}
                        </div>
                      </div>
                    </article>
                  );
                })}
                {tab !== 'trash' && (
                  <button type="button" className="md-new-app" onClick={() => navigate('studio')}>
                    <Plus size={25} />
                    <strong>Another idea?</strong>
                    <span>Ask for something new in Studio.</span>
                    <ArrowRight size={18} />
                  </button>
                )}
              </section>
            </>
          )}
          {view === 'device' && (
            <div className="md-device-grid">
              <section className="md-board-card">
                <div className="md-panel-heading">
                  <div>
                    <span className="md-eyebrow">YOUR VIRTUAL DEVICE</span>
                    <h2>Raspberry Pi workbench</h2>
                  </div>
                  <Badge>Simulation</Badge>
                </div>
                <div
                  className="md-circuit"
                  aria-label={`Virtual Raspberry Pi connected to ${workspace.modules.length} modules`}
                >
                  <div className="md-board">
                    <div className="md-pins">
                      {Array.from({ length: 20 }, (_, i) => (
                        <i key={i} />
                      ))}
                    </div>
                    <Cpu size={45} />
                    <strong>Raspberry Pi</strong>
                    <span>MODULATE RUNTIME</span>
                    <div className="md-ports">
                      <i />
                      <i />
                      <i />
                    </div>
                  </div>
                  <div className="md-wired-modules">
                    {MODULES.map((m) => (
                      <div key={m.id} className={workspace.modules.includes(m.id) ? 'is-wired' : ''}>
                        <i />
                        <span>{m.symbol}</span>
                        <strong>{m.name}</strong>
                        <small>{workspace.modules.includes(m.id) ? m.tag : 'Not attached'}</small>
                      </div>
                    ))}
                  </div>
                </div>
                <p className="md-board-note">
                  A conceptual component simulator, modeled on the physical prototype’s parts and
                  addresses. Wiring, electrical behavior and firmware are not emulated.
                </p>
              </section>
              <section className="md-hw" aria-labelledby="hw-title">
                <div className="md-panel-heading">
                  <div>
                    <span className="md-eyebrow">I²C BUS · SIMULATED</span>
                    <h2 id="hw-title">Hardware bench</h2>
                  </div>
                  <Wrench size={18} />
                </div>
                <table className="md-bus">
                  <tbody>
                    {hardwareReport(workspace).bus.map((d) => (
                      <tr key={d.address + d.device} className={d.status === 'ok' || d.status === 'driver ready' ? '' : 'is-fault'}>
                        <td>
                          <code>{d.address}</code>
                        </td>
                        <td>{d.device}</td>
                        <td>{d.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="md-hw-hint">Break something, then ask “Hey Meta, check my hardware.”</p>
                {faultButtons}
                {benchPanel}
              </section>
              <section className="md-parts">
                <div className="md-panel-heading">
                  <h2>Add your components</h2>
                  <Plus size={18} />
                </div>
                {componentTray}
                <Button
                  quiet
                  disabled={busy}
                  onClick={() => {
                    update(() => ({ modules: [...MODULES.map((m) => m.id), COMPUTER] }));
                    setNotice('All demo modules attached and the virtual Mac paired.');
                  }}
                >
                  Attach all components
                  <Plus size={14} />
                </Button>
              </section>
              <section className="md-device-summary">
                <div>
                  <h2>Your setup is yours.</h2>
                  <p>
                    {storageAvailable
                      ? 'Apps and components are saved in this browser, on this device. No account needed.'
                      : 'Browser storage is unavailable; changes will last only for this visit.'}
                  </p>
                </div>
                {showReset ? (
                  <div className="md-reset-confirm">
                    <span>Reset demo apps and components?</span>
                    <Button
                      danger
                      disabled={busy}
                      onClick={() => {
                        setWorkspace(freshWorkspace());
                        setPreviousId(null);
                        setShowReset(false);
                        setBench(null);
                        setMenu({ open: false, selected: 0 });
                        setNotice('Playground cleared. Ready for a new idea.');
                      }}
                    >
                      Reset playground
                    </Button>
                    <Button quiet onClick={() => setShowReset(false)}>
                      Keep my setup
                    </Button>
                  </div>
                ) : (
                  <Button quiet icon={RotateCcw} disabled={busy} onClick={() => setShowReset(true)}>
                    Start fresh
                  </Button>
                )}
              </section>
            </div>
          )}
          <footer className="md-footer">
            <span>
              <Monitor size={13} /> Ideas in the browser. Possibilities in your hands.
            </span>
            <Link href="/connect">
              Meet your real Modulate
              <ChevronRight size={14} />
            </Link>
          </footer>
        </main>
      </div>
    </div>
  );
}
