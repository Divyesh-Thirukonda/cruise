'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, ArrowRight, Check, CheckCircle2, Copy, Download, KeyRound, Loader2, ShieldCheck, X } from 'lucide-react';
import { Brand, Button, GadgetIllustration, Toggle } from './ui';
import { SETUP_PROMPT, SETUP_PLUGIN_URL } from './setup-content';
import metaLogo from './assets/meta.svg';

function EntryFrame({ children, navigate, back, step, urgentControls, className = '' }) {
  return <div className={`mc-app mf-entry ${className}`}>
    <header className="mf-header"><Link href="/connect" aria-label="Modulate home"><Brand /></Link>{back && <Button quiet icon={ArrowLeft} onClick={() => navigate(back)}>Back</Button>}</header>
    <main className="mf-main" id="mc-main">{urgentControls}{step && <div className="mf-steps" aria-label="Connection progress"><span className={step === 1 ? 'is-current' : 'is-complete'}>{step > 1 ? <Check size={13} /> : <i>1</i>}Connect</span><span className="mf-step-line" /><span className={step === 2 ? 'is-current' : ''}><i>2</i>Choose access</span></div>}{children}</main>
    <footer className="mf-footer"><img src={metaLogo.src || metaLogo} width={24} height={24} alt="" aria-hidden="true" /><span>Built with Meta AI</span></footer>
  </div>;
}

function Notice({ notice, onDismissNotice }) {
  return notice && <div className={`mc-notice mc-notice-${notice.type}`} role={notice.type === 'error' ? 'alert' : 'status'}><span>{notice.text}</span><button type="button" aria-label="Dismiss notification" onClick={onDismissNotice}><X size={16} /></button></div>;
}

export function ConnectionLanding({ loading, busy, notice, onDismissNotice, navigate, code, setCode, onConnect }) {
  return <EntryFrame navigate={navigate} className="mf-landing">
    <div className="mf-intro"><span className="mf-kicker">A NEW IDEA. THE SAME DEVICE.</span><h1>What will yours<br />become?</h1><p>A game. A music controller. Something only you imagined.<br className="mf-desktop-break" /> Connect Modulate, then say what you want to make.</p><GadgetIllustration /></div>
    <section className="mf-connect-panel" aria-labelledby="mf-connect-title">
      <div className="mf-step-label">LET’S GET CONNECTED</div><h2 id="mf-connect-title">Your Modulate, right here.</h2><p>Enter the 8-digit connection code shown on your device or in local Studio.</p>
      <form onSubmit={onConnect}>
        <label htmlFor="mc-connect-code">Connection code</label>
        <div className="mf-code-field"><KeyRound size={20} /><input id="mc-connect-code" autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{8}" placeholder="00000000" value={code} maxLength={8} onChange={event => setCode(event.target.value.replace(/\D/g, '').slice(0, 8))} aria-describedby="mf-code-hint" disabled={loading || Boolean(busy)} required /></div>
        <span id="mf-code-hint" className="mf-field-hint">Keep your Mac companion running while you connect.</span>
        <Notice notice={notice} onDismissNotice={onDismissNotice} />
        <Button primary type="submit" disabled={loading || code.length !== 8 || Boolean(busy)} icon={loading || busy === 'connect' ? Loader2 : undefined}>{loading ? 'Connecting' : busy === 'connect' ? 'Connecting…' : 'Connect to Modulate'}{!loading && busy !== 'connect' && <ArrowRight size={17} />}</Button>
      </form>
      <div className="mf-setup-link"><span>Don’t have a code yet?</span><Link href="/connect/setup" onClick={event => { event.preventDefault(); navigate('setup'); }}>Set up with Codex<ArrowRight size={15} /></Link></div>
    </section>
  </EntryFrame>;
}

export function SetupScreen({ navigate, connected, urgentControls, notice, onDismissNotice }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const copyPrompt = async () => {
    try { await navigator.clipboard.writeText(SETUP_PROMPT); setCopied(true); setCopyError(false); }
    catch { setCopyError(true); }
  };
  return <EntryFrame navigate={navigate} back={connected ? 'studio' : 'connect'} urgentControls={urgentControls} className="mf-setup">
    <Notice notice={notice} onDismissNotice={onDismissNotice} />
    <div className="mf-heading"><span className="mf-kicker">SET UP ON YOUR MAC</span><h1>A little help<br />getting started.</h1><p>Copy this prompt into Codex on your Mac.<br />It handles the software and guides you through the hands-on steps.</p></div>
    <section className="mf-prompt-card" aria-labelledby="mf-prompt-title"><div className="mf-card-label"><span className="mf-mini-mark">⌘</span><h2 id="mf-prompt-title">Let Codex take it from here.</h2></div><p>“Help me set up Modulate on this Mac and my Raspberry Pi. Reuse what’s already installed and guide me through anything that needs me.”</p><Button primary icon={copied ? Check : Copy} onClick={copyPrompt}>{copied ? 'Prompt copied' : 'Copy Codex prompt'}</Button><span className="mf-copy-hint" role="status">{copied ? 'Paste it into a new Codex chat on your Mac.' : 'Includes the setup guide and checks for your existing installation.'}</span><details open={copyError || undefined}><summary>{copyError ? 'Select and copy the full prompt below' : 'See the full prompt'}</summary><textarea aria-label="Codex setup prompt" readOnly value={SETUP_PROMPT} rows={9} onFocus={event => event.target.select()} /></details></section>
    <section className="mf-plugin-card"><div className="mf-plugin-icon"><Download size={22} /></div><div><h2>Keep the setup skill in Codex.</h2><p>Optional plugin for setup and connection troubleshooting.</p><details><summary>How to install</summary><p>Download and unzip it. Open the folder in Codex and ask it to install Modulate Setup. It adds a guided skill; it doesn’t run an installer or grant device access automatically.</p></details></div><a className="mc-button" href={SETUP_PLUGIN_URL} download>Download plugin<Download size={15} /></a></section>
    <p className="mf-setup-scope">This demo connects to one configured Modulate hub. Codex can help prepare a separate deployment for your own device.</p>
    <Button quiet icon={KeyRound} onClick={() => navigate(connected ? 'studio' : 'connect')}>{connected ? 'Back to Studio' : 'I have a connection code'}</Button>
  </EntryFrame>;
}

export function AccessStep({ navigate, permissions, choices, busy, online, notice, onDismissNotice, onSave, urgentControls }) {
  const [edits, setEdits] = useState({});
  const changed = Object.fromEntries(Object.entries(edits).filter(([key, value]) => value !== (permissions[key] === true)));
  const renderChoice = ({ key, title, detail, icon: Icon }) => <div className="mf-access-row" key={key}><Icon size={19} /><div><strong>{title}</strong><p>{detail}</p></div><Toggle label={`Allow ${title.toLowerCase()}`} checked={edits[key] ?? (permissions[key] === true)} disabled={Boolean(busy)} onChange={enabled => setEdits(previous => ({ ...previous, [key]: enabled }))} /></div>;
  return <EntryFrame navigate={navigate} step={2} urgentControls={urgentControls} className="mf-access">
    <div className="mf-heading"><span className="mf-success"><CheckCircle2 size={18} />Browser connected</span><h1>Make it yours.</h1><p>Review what Modulate can use. These are your device’s current settings.<br />You can change them later in Access.</p></div>
    <Notice notice={notice} onDismissNotice={onDismissNotice} />
    {!online && <div className="mc-notice mc-notice-warning" role="status">The companion is offline. Keep Studio running on your Mac to save access changes.</div>}
    <section className="mf-access-card"><h2>On your Modulate</h2>{choices.filter(({ key }) => ['voice', 'speaker', 'hardware'].includes(key)).map(renderChoice)}</section>
    <section className="mf-access-card"><h2>With your Mac</h2>{choices.filter(({ key }) => ['system', 'computer', 'camera', 'audio'].includes(key)).map(renderChoice)}</section>
    <details className="mf-access-extra"><summary>Share camera previews with this browser</summary>{choices.filter(({ key }) => key === 'remote_preview').map(renderChoice)}</details>
    <p className="mf-access-note"><ShieldCheck size={17} />Changes apply to your Modulate across voice and all linked browsers. macOS permissions are still granted on your Mac.</p>
    <div className="mf-access-actions"><Button quiet disabled={Boolean(busy)} onClick={() => navigate('studio')}>Keep current access</Button><Button primary disabled={!online || Boolean(busy)} onClick={() => Object.keys(changed).length ? onSave(changed) : navigate('studio')}>{busy === 'access' ? 'Saving…' : 'Save & open Studio'}<ArrowRight size={16} /></Button></div>
  </EntryFrame>;
}
