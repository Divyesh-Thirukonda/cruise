'use client';

import React, { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  ArrowRight,
  Check,
  ChevronRight,
  Cpu,
  FlaskConical,
  Gamepad2,
  LayoutDashboard,
  Library,
  Loader2,
  Plus,
  RotateCcw,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { Badge, Brand, Button } from '../ui';
import VirtualDevice from './VirtualDevice';
import {
  checkApp,
  freshWorkspace,
  MODULES,
  SUGGESTIONS,
  restoreWorkspace,
  STORAGE_KEY,
} from './model';
import '../connect.css';
import './demo.css';

const NAV = [
  ['studio', LayoutDashboard, 'Studio'],
  ['library', Library, 'App library'],
  ['device', Cpu, 'Device'],
];

export default function Demo() {
  const [workspace, setWorkspace] = useState(freshWorkspace);
  const [ready, setReady] = useState(false);
  const [storageAvailable, setStorageAvailable] = useState(true);
  const [view, setView] = useState('studio');
  const [request, setRequest] = useState('');
  const [notice, setNotice] = useState('');
  const [build, setBuild] = useState(null);
  const [candidate, setCandidate] = useState(null);
  const generation = useRef(null);
  const [previousId, setPreviousId] = useState(null);
  const [rename, setRename] = useState(null);
  const [showReset, setShowReset] = useState(false);
  const main = useRef(null);
  const active = workspace.apps.find((app) => app.id === workspace.activeId);
  const busy = Boolean(build);

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
  const activate = (app) => {
    setPreviousId(workspace.activeId);
    setWorkspace((current) => ({
      ...current,
      apps: current.apps.some((a) => a.id === app.id) ? current.apps : [...current.apps, app],
      activeId: app.id,
    }));
    setCandidate(null);
    setBuild(null);
    setRequest('');
    setNotice(`${app.title} passed the checks and is ready. Press Play app.`);
  };
  const reject = (message) => {
    setCandidate(null);
    setBuild(null);
    setNotice(`${message} Your previous app is kept.`);
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
    setWorkspace((current) => ({
      ...current,
      modules: current.modules.includes(id)
        ? current.modules.filter((m) => m !== id)
        : [...current.modules, id],
    }));
  };
  const loadApp = (app) => {
    if (busy) return;
    const error = checkApp(app, workspace.modules);
    if (error) {
      setNotice(error);
      return;
    }
    if (app.id !== workspace.activeId) {
      setCandidate(app);
      setBuild({ phase: 'Checking saved app on your virtual device…' });
    }
    navigate('studio');
  };
  const create = async (event) => {
    event.preventDefault();
    if (busy || !request.trim()) return;
    if (!workspace.modules.includes('display')) {
      setNotice('Attach a display before generating an app.');
      return;
    }
    if (workspace.apps.length >= 24) {
      setNotice('Your demo library is full. Remove an unused app to make room.');
      return;
    }
    const controller = new AbortController();
    generation.current = controller;
    setNotice('');
    setBuild({ phase: 'Connecting to Meta…' });
    try {
      const sessionResponse = await fetch('/api/demo', { signal: controller.signal });
      const session = await sessionResponse.json();
      if (!sessionResponse.ok) throw Error(session.error);
      const response = await fetch('/api/demo', {
        method: 'POST',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-Demo-CSRF': session.csrf },
        body: JSON.stringify({
          prompt: request.trim(),
          modules: workspace.modules,
          previous: active
            ? {
                title: active.title,
                description: active.description,
                requires: active.requires,
                controls: active.controls,
                code: active.code,
              }
            : null,
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
          if (message.type === 'error') throw Error(message.error);
          if (message.type === 'result') result = message;
        }
      }
      if (generation.current !== controller) return;
      if (!result) throw Error('Generation ended without a verified app.');
      const app = {
        ...result.app,
        id: result.revision,
        checks: result.checks,
        review: result.review,
        inference: result.inference,
      };
      const error = checkApp(app, workspace.modules);
      if (error) throw Error(error);
      setBuild({ phase: 'Waiting for virtual device verification…' });
      setCandidate(app);
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
        return (
          <button
            className={`md-module ${connected ? 'is-attached' : ''}`}
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
              <small>{module.detail}</small>
            </span>
            <span className="md-module-state">
              {connected ? <Check size={15} /> : <Plus size={15} />}
            </span>
          </button>
        );
      })}
    </div>
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
              {id === 'library' && <small>{workspace.apps.length}</small>}
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
          <span className="md-topbar-detail">All yours. All virtual.</span>
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
                  ? 'Small device. Endless possibility.'
                  : view === 'library'
                    ? 'A few ideas. All yours.'
                    : 'Build your little machine.'}
              </h1>
              <p>
                {view === 'studio'
                  ? 'Plug in a few components. Give them a new job. See what happens.'
                  : view === 'library'
                    ? 'Switch apps, remix an idea, or pick up where you left off.'
                    : 'Click a module to attach or remove it. Your controls change with your setup.'}
              </p>
            </div>
            <Badge>Live Meta AI</Badge>
          </div>
          <div className="md-disclosure">
            <FlaskConical size={16} />
            <p>
              Real Meta inference. Virtual hardware.{' '}
              <span>
                Your typed request goes to Meta Muse Spark to generate and review original app code.
                Checked apps run locally. No physical device needed.
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
                Write → check → Meta review → device verification. Your current app is kept until
                activation.
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
                      <h2 id="bench-title">{active?.title || 'Your next idea'}</h2>
                    </div>
                    <span className="md-pi-chip">
                      <Cpu size={14} />
                      Raspberry Pi
                    </span>
                  </div>
                  <VirtualDevice
                    app={active}
                    candidate={candidate}
                    modules={workspace.modules}
                    busy={busy || !ready}
                    onReady={activate}
                    onReject={reject}
                  />
                  <div className="md-bench-bottom">
                    <span>
                      <i />
                      {workspace.modules.length} modules attached
                    </span>
                    <Button
                      quiet
                      icon={RotateCcw}
                      disabled={!previousId || busy}
                      onClick={rollback}
                    >
                      Restore previous app
                    </Button>
                  </div>
                </section>
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
                      Try a different setup.
                      <br />
                      <strong>Meta writes for attached parts.</strong>
                    </p>
                  </div>
                  <button type="button" className="md-text-link" onClick={() => navigate('device')}>
                    Explore your device
                    <ArrowRight size={14} />
                  </button>
                </section>
              </div>
              {active && (
                <details className="md-evidence">
                  <summary>
                    Code & checks · {active.inference?.model} · {active.inference?.calls?.length}{' '}
                    live calls
                  </summary>
                  <p>{active.review}</p>
                  <p>
                    {active.checks?.frames} server frames checked, plus browser verification. Typed
                    input · {active.inference?.seconds}s generation. Revision:{' '}
                    <code>{active.id}</code>
                  </p>
                  <ul>
                    {active.inference?.calls?.map((call, i) => (
                      <li key={i}>
                        {call.model} · {call.usage.prompt_tokens} input /{' '}
                        {call.usage.completion_tokens} output tokens · response{' '}
                        <code>{call.responseId || 'ID unavailable'}</code>
                      </li>
                    ))}
                  </ul>
                  <pre>
                    <code>{active.code}</code>
                  </pre>
                </details>
              )}
              <section className="md-composer">
                <div className="md-composer-intro">
                  <span className="md-spark">
                    <Sparkles size={23} />
                  </span>
                  <div>
                    <h2>Same hardware. A new idea.</h2>
                    <p>
                      Describe anything these components can do. Or ask for a change to your current
                      app.
                    </p>
                  </div>
                  <span className="md-example-tag">LIVE GENERATION</span>
                </div>
                <form onSubmit={create}>
                  <label className="mc-sr-only" htmlFor="demo-request">
                    Demo request
                  </label>
                  <input
                    id="demo-request"
                    value={request}
                    maxLength={1200}
                    disabled={busy || !ready}
                    onChange={(e) => setRequest(e.target.value)}
                    placeholder="Make a little racing game…"
                  />
                  <Button primary type="submit" disabled={busy || !ready || !request.trim()}>
                    {busy ? 'Generating…' : 'Generate app'}
                    <ArrowRight size={16} />
                  </Button>
                </form>
                <div className="md-suggestions">
                  {[
                    ...SUGGESTIONS,
                    [
                      'Remix this app',
                      'Make the current app more colorful and add a surprising new feature using its attached components.',
                    ],
                  ].map(([label, prompt]) => (
                    <button
                      type="button"
                      key={label}
                      disabled={busy}
                      onClick={() => setRequest(prompt)}
                    >
                      {label}
                      <Plus size={12} />
                    </button>
                  ))}
                </div>
              </section>
            </>
          )}
          {view === 'library' && (
            <section className="md-library" aria-label="Your demo apps">
              {workspace.apps.map((app) => {
                const selected = app.id === workspace.activeId;
                return (
                  <article
                    key={app.id}
                    className="md-app-card"
                    style={{ '--app-color': '#a8b8ff' }}
                  >
                    <div className="md-app-art md-art-orbit" aria-hidden="true">
                      <span>✦</span>
                      <i />
                      <b>✧</b>
                      <small>META GENERATED APP</small>
                    </div>
                    <div className="md-app-card-body">
                      {rename?.id === app.id ? (
                        <form
                          onSubmit={(e) => {
                            e.preventDefault();
                            if (rename.title.trim()) {
                              setWorkspace((w) => ({
                                ...w,
                                apps: w.apps.map((a) =>
                                  a.id === app.id ? { ...a, title: rename.title.trim() } : a,
                                ),
                              }));
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
                          <h2>{app.title}</h2>
                          <p>{app.description}</p>
                        </>
                      )}
                      <div className="md-app-card-meta">
                        <span>{app.inference?.calls?.length || 0} Meta calls · checked</span>
                        <span>{selected ? 'On device' : 'Saved app'}</span>
                      </div>
                      <div className="md-library-actions">
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
                          disabled={busy}
                          onClick={() => setRename({ id: app.id, title: app.title })}
                        >
                          Rename
                        </Button>
                        <Button
                          quiet
                          icon={Trash2}
                          aria-label={`Remove ${app.title}`}
                          disabled={selected || busy}
                          onClick={() => {
                            setWorkspace((w) => ({
                              ...w,
                              apps: w.apps.filter((a) => a.id !== app.id),
                            }));
                            if (previousId === app.id) setPreviousId(null);
                            setNotice(`${app.title} removed from your demo library.`);
                          }}
                        />
                      </div>
                    </div>
                  </article>
                );
              })}
              <button type="button" className="md-new-app" onClick={() => navigate('studio')}>
                <Plus size={25} />
                <strong>Another idea?</strong>
                <span>Generate something new in Studio.</span>
                <ArrowRight size={18} />
              </button>
            </section>
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
                      <div
                        key={m.id}
                        className={workspace.modules.includes(m.id) ? 'is-wired' : ''}
                      >
                        <i />
                        <span>{m.symbol}</span>
                        <strong>{m.name}</strong>
                        <small>{workspace.modules.includes(m.id) ? m.tag : 'Not attached'}</small>
                      </div>
                    ))}
                  </div>
                </div>
                <p className="md-board-note">
                  A conceptual component simulator, inspired by the Pi-powered prototype. Wiring,
                  electrical behavior, and firmware are not emulated. Arduino hardware is not
                  connected or supported by this demo.
                </p>
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
                    setWorkspace((w) => ({ ...w, modules: MODULES.map((m) => m.id) }));
                    setNotice('All five demo modules attached.');
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
            <span>Ideas in the browser. Possibilities in your hands.</span>
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
