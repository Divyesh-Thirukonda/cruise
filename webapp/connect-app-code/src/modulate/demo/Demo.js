'use client';

import React, { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { ArrowRight, Check, ChevronRight, Cpu, FlaskConical, Gamepad2, LayoutDashboard, Library, Loader2, Plus, RotateCcw, Sparkles, Trash2, X } from 'lucide-react';
import { Badge, Brand, Button } from '../ui';
import VirtualDevice from './VirtualDevice';
import { checkApp, COLORS, freshWorkspace, interpretRequest, MODULES, RECIPES, restoreWorkspace, STORAGE_KEY } from './model';
import '../connect.css';
import './demo.css';

const NAV = [['studio', LayoutDashboard, 'Studio'], ['library', Library, 'App library'], ['device', Cpu, 'Device']];
const STEPS = ['Read connected components', 'Check example & controls', 'Activate virtual device'];

export default function Demo() {
  const [workspace, setWorkspace] = useState(freshWorkspace);
  const [ready, setReady] = useState(false);
  const [storageAvailable, setStorageAvailable] = useState(true);
  const [view, setView] = useState('studio');
  const [request, setRequest] = useState('');
  const [notice, setNotice] = useState('');
  const [build, setBuild] = useState(null);
  const [previousId, setPreviousId] = useState(null);
  const [rename, setRename] = useState(null);
  const [showReset, setShowReset] = useState(false);
  const main = useRef(null);
  const active = workspace.apps.find(app => app.id === workspace.activeId);
  const busy = Boolean(build);

  useEffect(() => {
    // The legacy Connect layout restores its title on unmount during client navigation.
    document.title = 'Modulate Playground — Try a virtual device';
    try { setWorkspace(restoreWorkspace(localStorage.getItem(STORAGE_KEY))); }
    catch { setStorageAvailable(false); }
    setReady(true);
  }, []);
  useEffect(() => {
    if (!ready) return;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(workspace)); }
    catch { setStorageAvailable(false); }
  }, [workspace, ready]);
  useEffect(() => {
    if (!build) return;
    const timer = setTimeout(() => {
      if (build.step < 2) { setBuild({ ...build, step: build.step + 1 }); return; }
      const error = checkApp(build.app, workspace.modules);
      if (error) setNotice(`${error} The previous app is still selected.`);
      else {
        setPreviousId(workspace.activeId);
        setWorkspace(current => ({ ...current, apps: [...current.apps, build.app], activeId: build.app.id }));
        setNotice(`${build.app.title} is ready. Saved to your demo library.`);
        setRequest('');
      }
      setBuild(null);
    }, 500);
    return () => clearTimeout(timer);
  }, [build, workspace.modules, workspace.activeId]);

  const navigate = next => { setView(next); setRename(null); main.current?.scrollTo?.({ top: 0 }); };
  const toggleModule = id => {
    if (busy) return;
    setWorkspace(current => ({ ...current, modules: current.modules.includes(id) ? current.modules.filter(m => m !== id) : [...current.modules, id] }));
  };
  const loadApp = app => {
    if (busy) return;
    const error = checkApp(app, workspace.modules);
    if (error) { setNotice(error); return; }
    if (app.id !== workspace.activeId) setPreviousId(workspace.activeId);
    setWorkspace(current => ({ ...current, activeId: app.id }));
    setNotice(`${app.title} is on your virtual device.`);
    navigate('studio');
  };
  const create = event => {
    event.preventDefault();
    if (busy || !request.trim()) return;
    const result = interpretRequest(request, active);
    if (!result) { setNotice('This playground supports star-catching, racing, synths, colors (blue, pink, yellow, green), and faster/slower edits. Try one below. Open-ended Meta generation runs on a real Modulate.'); return; }
    if (workspace.apps.length >= 24) { setNotice('Your demo library is full. Remove an unused app to make room.'); return; }
    const app = { ...result, id: `demo-${crypto.randomUUID()}` };
    const error = checkApp(app, workspace.modules);
    if (error) { setNotice(`${error} Add it in the component tray, then try again.`); return; }
    setNotice(''); setBuild({ app, step: 0 });
  };
  const rollback = () => {
    const previous = workspace.apps.find(app => app.id === previousId);
    if (previous) loadApp(previous);
  };
  const componentTray = <div className="md-module-list">{MODULES.map(module => {
    const connected = workspace.modules.includes(module.id);
    return <button className={`md-module ${connected ? 'is-attached' : ''}`} key={module.id} type="button" aria-pressed={connected} aria-label={`${connected ? 'Remove' : 'Attach'} ${module.name.toLowerCase()}`} disabled={busy || !ready} onClick={() => toggleModule(module.id)}><span className={`md-module-symbol md-symbol-${module.id}`}>{module.symbol}</span><span className="md-module-copy"><strong>{module.name}</strong><small>{module.detail}</small></span><span className="md-module-state">{connected ? <Check size={15} /> : <Plus size={15} />}</span></button>;
  })}</div>;

  return <div className="mc-app md-app">
    <a href="#demo-main" className="mc-skip">Skip to playground</a>
    <aside className="md-sidebar">
      <Link href="/connect" aria-label="Modulate home"><Brand /></Link>
      <div className="md-workspace"><div className="md-workspace-icon"><FlaskConical size={21} /></div><div><strong>Your playground</strong><span>No hardware required</span></div></div>
      <span className="mc-nav-label">WORKSPACE</span>
      <nav aria-label="Demo workspace">{NAV.map(([id, Icon, title]) => <button type="button" key={id} className={view === id ? 'is-selected' : ''} aria-current={view === id ? 'page' : undefined} onClick={() => navigate(id)}><Icon size={18} /><span>{title}</span>{id === 'library' && <small>{workspace.apps.length}</small>}</button>)}</nav>
      <div className="md-sidebar-bottom"><span className="md-local-dot" />{storageAvailable ? 'Saved in this browser' : 'Session only · storage unavailable'}<p>Your own apps. Your own setup.<br />Come back and keep tinkering.</p><Link href="/connect">Connect real hardware<ArrowRight size={14} /></Link></div>
    </aside>
    <div className="md-shell" ref={main}>
      <header className="md-topbar"><span><FlaskConical size={15} />ONLINE DEMO</span><span className="md-topbar-detail">All yours. All virtual.</span><Link href="/connect">Exit demo<X size={15} /></Link></header>
      <main id="demo-main" className="md-main" tabIndex={-1}>
        <div className="md-heading"><div><span className="md-eyebrow">THE MODULATE PLAYGROUND</span><h1>{view === 'studio' ? 'Small device. Endless possibility.' : view === 'library' ? 'A few ideas. All yours.' : 'Build your little machine.'}</h1><p>{view === 'studio' ? 'Plug in a few components. Give them a new job. See what happens.' : view === 'library' ? 'Switch apps, remix an example, or pick up where you left off.' : 'Click a module to attach or remove it. Your controls change with your setup.'}</p></div><Badge>Browser simulation</Badge></div>
        <div className="md-disclosure"><FlaskConical size={16} /><p>A hands-on preview with built-in examples. Real Modulate uses Meta AI to create apps from your voice. <span>This demo runs locally with no AI calls, microphone access, or hardware connection.</span></p></div>
        {!ready && <p role="status">Opening your playground…</p>}
        {notice && <div className="md-notice" role="status"><span>{notice}</span><button type="button" aria-label="Dismiss demo message" onClick={() => setNotice('')}><X size={16} /></button></div>}
        {build && <div className="md-build" role="status"><div><Loader2 className="md-spin" size={18} /><strong>Demo walkthrough</strong><Button quiet onClick={() => { setBuild(null); setNotice('Cancelled. Your previous app is kept.'); }}>Cancel</Button></div><ol>{STEPS.map((step, i) => <li key={step} className={i <= build.step ? 'is-done' : ''}>{i < build.step ? <Check size={13} /> : <span>{i + 1}</span>}{step}</li>)}</ol></div>}
        {view === 'studio' && <>
          <div className="md-studio-grid">
            <section className="md-bench" aria-labelledby="bench-title"><div className="md-panel-heading"><div><span className="md-eyebrow">ON YOUR DEVICE</span><h2 id="bench-title">{active.title}</h2></div><span className="md-pi-chip"><Cpu size={14} />Raspberry Pi</span></div><VirtualDevice key={active.id} app={active} modules={workspace.modules} busy={busy || !ready} /><div className="md-bench-bottom"><span><i />{workspace.modules.length} modules attached</span><Button quiet icon={RotateCcw} disabled={!previousId || busy} onClick={rollback}>Restore previous app</Button></div></section>
            <section className="md-parts" aria-labelledby="parts-title"><div className="md-panel-heading"><div><span className="md-eyebrow">MAKE IT MODULAR</span><h2 id="parts-title">Your components</h2></div><Cpu size={19} /></div>{componentTray}<div className="md-tip"><Sparkles size={16} /><p>Try removing the joystick.<br /><strong>The knob can steer, too.</strong></p></div><button type="button" className="md-text-link" onClick={() => navigate('device')}>Explore your device<ArrowRight size={14} /></button></section>
          </div>
          <section className="md-composer"><div className="md-composer-intro"><span className="md-spark"><Sparkles size={23} /></span><div><h2>Same hardware. A new idea.</h2><p>Try an example request, then make it faster or change its color.</p></div><span className="md-example-tag">EXAMPLE MODE</span></div><form onSubmit={create}><label className="mc-sr-only" htmlFor="demo-request">Demo request</label><input id="demo-request" value={request} maxLength={240} disabled={busy || !ready} onChange={e => setRequest(e.target.value)} placeholder="Make a little racing game…" /><Button primary type="submit" disabled={busy || !ready || !request.trim()}>{busy ? 'Preparing…' : 'Try request'}<ArrowRight size={16} /></Button></form><div className="md-suggestions">{[...RECIPES.map(r => [r.label, r.prompt]), ['Make it pink', 'Make it pink'], ['A little faster', 'Make it faster']].map(([label, prompt]) => <button type="button" key={label} disabled={busy} onClick={() => setRequest(prompt)}>{label}<Plus size={12} /></button>)}</div></section>
        </>}
        {view === 'library' && <section className="md-library" aria-label="Your demo apps">{workspace.apps.map(app => {
          const selected = app.id === workspace.activeId;
          return <article key={app.id} className="md-app-card" style={{ '--app-color': COLORS[app.color] }}><div className={`md-app-art md-art-${app.kind}`} aria-hidden="true">{app.kind === 'orbit' ? <><span>✦</span><i /><b>✧</b></> : app.kind === 'rally' ? <><i /><span>▰</span><b>▰</b></> : <span>∿∿∿</span>}<small>{app.kind === 'synth' ? 'INSTRUMENT' : 'PLAYABLE GAME'}</small></div><div className="md-app-card-body">{rename?.id === app.id ? <form onSubmit={e => { e.preventDefault(); if (rename.title.trim()) { setWorkspace(w => ({ ...w, apps: w.apps.map(a => a.id === app.id ? { ...a, title: rename.title.trim() } : a) })); setRename(null); } }}><label className="mc-sr-only" htmlFor="demo-app-name">App name</label><input id="demo-app-name" autoFocus maxLength={60} value={rename.title} onChange={e => setRename({ ...rename, title: e.target.value })} /><Button type="submit">Save</Button><Button type="button" quiet onClick={() => setRename(null)}>Cancel</Button></form> : <><h2>{app.title}</h2><p>{RECIPES.find(r => r.kind === app.kind).description}</p></>}<div className="md-app-card-meta"><span>{app.speed === 1.5 ? 'Fast' : app.speed === 0.7 ? 'Easy' : 'Classic'} · {app.color}</span><span>{selected ? 'On device' : 'Saved example'}</span></div><div className="md-library-actions"><Button primary={selected} disabled={busy} icon={Gamepad2} onClick={() => loadApp(app)}>{selected ? 'Back to app' : 'Open app'}</Button><Button quiet disabled={busy} onClick={() => setRename({ id: app.id, title: app.title })}>Rename</Button><Button quiet icon={Trash2} aria-label={`Remove ${app.title}`} disabled={selected || busy} onClick={() => { setWorkspace(w => ({ ...w, apps: w.apps.filter(a => a.id !== app.id) })); if (previousId === app.id) setPreviousId(null); setNotice(`${app.title} removed from your demo library.`); }} /></div></div></article>;
        })}<button type="button" className="md-new-app" onClick={() => navigate('studio')}><Plus size={25} /><strong>Another idea?</strong><span>Remix an example in Studio.</span><ArrowRight size={18} /></button></section>}
        {view === 'device' && <div className="md-device-grid"><section className="md-board-card"><div className="md-panel-heading"><div><span className="md-eyebrow">YOUR VIRTUAL DEVICE</span><h2>Raspberry Pi workbench</h2></div><Badge>Simulation</Badge></div><div className="md-circuit" aria-label={`Virtual Raspberry Pi connected to ${workspace.modules.length} modules`}><div className="md-board"><div className="md-pins">{Array.from({ length: 20 }, (_, i) => <i key={i} />)}</div><Cpu size={45} /><strong>Raspberry Pi</strong><span>MODULATE RUNTIME</span><div className="md-ports"><i /><i /><i /></div></div><div className="md-wired-modules">{MODULES.map(m => <div key={m.id} className={workspace.modules.includes(m.id) ? 'is-wired' : ''}><i /><span>{m.symbol}</span><strong>{m.name}</strong><small>{workspace.modules.includes(m.id) ? m.tag : 'Not attached'}</small></div>)}</div></div><p className="md-board-note">A conceptual component simulator, inspired by the Pi-powered prototype. Wiring, electrical behavior, and firmware are not emulated. Arduino hardware is not connected or supported by this demo.</p></section><section className="md-parts"><div className="md-panel-heading"><h2>Add your components</h2><Plus size={18} /></div>{componentTray}<Button quiet disabled={busy} onClick={() => { setWorkspace(w => ({ ...w, modules: MODULES.map(m => m.id) })); setNotice('All five demo modules attached.'); }}>Attach all components<Plus size={14} /></Button></section><section className="md-device-summary"><div><h2>Your setup is yours.</h2><p>{storageAvailable ? 'Apps and components are saved in this browser, on this device. No account needed.' : 'Browser storage is unavailable; changes will last only for this visit.'}</p></div>{showReset ? <div className="md-reset-confirm"><span>Reset demo apps and components?</span><Button danger disabled={busy} onClick={() => { setWorkspace(freshWorkspace()); setPreviousId(null); setShowReset(false); setNotice('Playground reset to the three starter apps.'); }}>Reset playground</Button><Button quiet onClick={() => setShowReset(false)}>Keep my setup</Button></div> : <Button quiet icon={RotateCcw} disabled={busy} onClick={() => setShowReset(true)}>Start fresh</Button>}</section></div>}
        <footer className="md-footer"><span>Ideas in the browser. Possibilities in your hands.</span><Link href="/connect">Meet your real Modulate<ChevronRight size={14} /></Link></footer>
      </main>
    </div>
  </div>;
}
