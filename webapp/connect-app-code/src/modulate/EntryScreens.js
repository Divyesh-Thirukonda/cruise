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

function Notice({ notice, onDismissNotice, onSetup }) {
  return notice && <div className={`mc-notice mc-notice-${notice.type}`} role={notice.type === 'error' ? 'alert' : 'status'}><span>{notice.text}{notice.setupHelp && onSetup && <button className="mf-notice-action" type="button" onClick={onSetup}>Set up your Mac<ArrowRight size={14} /></button>}</span><button type="button" aria-label="Dismiss notification" onClick={onDismissNotice}><X size={16} /></button></div>;
}

export function ConnectionUnavailable({ onSetup }) {
  return <div className="mc-notice mc-notice-warning" role="status"><span>Your Modulate connection isn’t reachable yet. Ask your setup agent to finish or reconnect it.{onSetup && <button className="mf-notice-action" type="button" onClick={onSetup}>Get connection help<ArrowRight size={14} /></button>}</span></div>;
}

export function ConnectionLanding({ standalone = false, loading, busy, notice, onDismissNotice, connectionUnavailable, navigate, code, setCode, onConnect }) {
  return <EntryFrame navigate={navigate} className="mf-landing">
    <div className="mf-intro"><span className="mf-kicker">A NEW IDEA. THE SAME DEVICE.</span><h1>What will yours<br />become?</h1><p>A game. A music controller. Something only you imagined.<br className="mf-desktop-break" /> Speak to Modulate to make it. Link this browser when you want a dashboard.</p><GadgetIllustration /></div>
    <section className="mf-connect-panel" aria-labelledby="mf-connect-title">
      <div className="mf-step-label">LET’S GET CONNECTED</div><h2 id="mf-connect-title">Your Modulate, right here.</h2>
      <div className="mf-setup-link"><span>{standalone ? 'No Mac needed.' : 'First time?'}</span> <Link href="/connect/setup" onClick={event => { event.preventDefault(); navigate('setup'); }}>{standalone ? 'Find your device code' : 'Set up your Mac'}</Link></div>
      <form onSubmit={onConnect}>
        <label htmlFor="mc-connect-code">{standalone ? 'Enter the code shown on Modulate' : 'Back from setup? Enter your connection code'}</label>
        <div className="mf-code-field"><KeyRound size={20} /><input id="mc-connect-code" autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{8}" placeholder="00000000" value={code} maxLength={8} onChange={event => setCode(event.target.value.replace(/\D/g, '').slice(0, 8))} disabled={loading || Boolean(busy)} required /></div>
        {connectionUnavailable && !notice && <ConnectionUnavailable onSetup={() => navigate('setup')} />}
        <Notice notice={notice} onDismissNotice={onDismissNotice} onSetup={() => navigate('setup')} />
        <Button primary type="submit" disabled={loading || code.length !== 8 || Boolean(busy)} icon={loading || busy === 'connect' ? Loader2 : undefined}>{loading ? 'Connecting' : busy === 'connect' ? 'Connecting…' : 'Connect to Modulate'}{!loading && busy !== 'connect' && <ArrowRight size={17} />}</Button>
      </form>
    </section>
  </EntryFrame>;
}

export function SetupScreen({ standalone = false, navigate, connected, urgentControls, notice, onDismissNotice, connectionUnavailable }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const copyPrompt = async () => {
    try { await navigator.clipboard.writeText(SETUP_PROMPT); setCopied(true); setCopyError(false); }
    catch { setCopyError(true); }
  };
  if (standalone) return <EntryFrame navigate={navigate} back={connected ? 'studio' : 'connect'} urgentControls={urgentControls} className="mf-setup">
    <Notice notice={notice} onDismissNotice={onDismissNotice} />
    <div className="mf-heading"><span className="mf-kicker">YOUR DEVICE. ITS OWN AI.</span><h1>Just Modulate<br />and Wi-Fi.</h1><p>Speak to create apps and hear replies without a Mac. Connect this browser when you want to manage your device.</p></div>
    <section className="mf-prompt-card"><h2>Get your connection code.</h2><p>Hold the small A button on Modulate for one second to open setup. Release it, then press A to show a one-use browser code. Enter that code here.</p><p>This eight-digit code links only your browser. Enter it on the website; it does not grant native Mac access.</p></section>
    <Button primary icon={ArrowRight} onClick={() => navigate('connect')}>Enter device code</Button>
    <section className="mf-prompt-card"><h2>Optional: connect this Mac.</h2><p>For brightness, volume, desktop actions, camera or computer audio, copy this prompt into your coding agent on the Mac. It installs or reconnects the native helper.</p><Button primary icon={copied ? Check : Copy} onClick={copyPrompt}>{copied ? 'Prompt copied' : 'Copy Mac setup prompt'}</Button><details open={copyError || undefined}><summary>See the full prompt</summary><textarea aria-label="Agent setup prompt" readOnly value={SETUP_PROMPT} rows={9} onFocus={event => event.target.select()} /></details><p>The helper and Modulate show a matching eight-digit comparison code. Compare them and press small A on Modulate. You do not type that comparison code into the website.</p><p>Temporary disconnections reconnect within the existing eight-hour session. After expiry or revocation, pair again. Your device keeps working on its own.</p></section>
  </EntryFrame>;
  return <EntryFrame navigate={navigate} back={connected ? 'studio' : 'connect'} urgentControls={urgentControls} className="mf-setup">
    <Notice notice={notice} onDismissNotice={onDismissNotice} />
    {connectionUnavailable && !notice && <ConnectionUnavailable />}
    <div className="mf-heading"><span className="mf-kicker">SET UP ON YOUR MAC</span><h1>First, set up<br />your Mac.</h1><p>Your Modulate comes with its device software installed.<br />Power it on and connect it to the same network as your Mac.</p></div>
    <section className="mf-prompt-card" aria-labelledby="mf-prompt-title"><div className="mf-card-label"><span className="mf-mini-mark">⌘</span><h2 id="mf-prompt-title">Let your agent handle setup.</h2></div><p>Paste this prompt into your coding agent on this Mac. It prepares the connection and opens a simple screen when your gadget needs confirmation.</p><Button primary icon={copied ? Check : Copy} onClick={copyPrompt}>{copied ? 'Prompt copied' : 'Copy setup prompt'}</Button><span className="mf-copy-hint" role="status">{copied ? 'Next: paste it into your coding agent on the Mac you want to connect.' : 'The prompt is all you need to begin. The plugin below is optional.'}</span><details open={copyError || undefined}><summary>{copyError ? 'Select and copy the full prompt below' : 'See the full prompt'}</summary><textarea aria-label="Agent setup prompt" readOnly value={SETUP_PROMPT} rows={9} onFocus={event => event.target.select()} /></details></section>
    <p className="mf-setup-next"><CheckCircle2 size={18} /><span><strong>Confirm on your gadget. Finish here.</strong>Compare the matching details, then press A on your gadget. Your agent brings you back to this website with a browser connection code. Enter it, then choose your access.</span></p>
    <Button primary icon={ArrowRight} onClick={() => navigate('connect')}>{connected ? 'Return to your device' : 'Return to connection'}</Button>
    <section className="mf-plugin-card"><div className="mf-plugin-icon"><Download size={22} /></div><div><h2>Give your agent the setup skill.</h2><p>Optional plugin for setup and connection troubleshooting.</p><details><summary>How to install</summary><p>Download and unzip it. Open the folder in your coding agent and ask it to follow the Modulate Setup skill. You can also add it through your agent’s skill installation flow. It doesn’t grant device access automatically.</p></details></div><a className="mc-button" href={SETUP_PLUGIN_URL} download>Download plugin<Download size={15} /></a></section>
    <p className="mf-setup-scope">This guide is for a preloaded Modulate on a working network. Older device software may need an update first. This demo connects to one configured hub; your agent will provide the correct link for your installation.</p>
  </EntryFrame>;
}

export function AccessStep({ navigate, permissions, choices, busy, online, notice, onDismissNotice, onSave, urgentControls }) {
  const [edits, setEdits] = useState({});
  const changed = Object.fromEntries(Object.entries(edits).filter(([key, value]) => value !== (permissions[key] === true)));
  const renderChoice = ({ key, title, detail, icon: Icon }) => <div className="mf-access-row" key={key}><Icon size={19} /><div><strong>{title}</strong><p>{detail}</p></div><Toggle label={`Allow ${title.toLowerCase()}`} checked={edits[key] ?? (permissions[key] === true)} disabled={Boolean(busy)} onChange={enabled => setEdits(previous => ({ ...previous, [key]: enabled }))} /></div>;
  return <EntryFrame navigate={navigate} step={2} urgentControls={urgentControls} className="mf-access">
    <div className="mf-heading"><span className="mf-success"><CheckCircle2 size={18} />Browser connected</span><h1>Make it yours.</h1><p>Review what Modulate can use. These are your device’s current settings.<br />You can change them later in Access.</p></div>
    <Notice notice={notice} onDismissNotice={onDismissNotice} />
    {!online && <ConnectionUnavailable onSetup={() => navigate('setup')} />}
    <section className="mf-access-card"><h2>On your Modulate</h2>{choices.filter(({ key }) => ['voice', 'speaker', 'hardware'].includes(key)).map(renderChoice)}</section>
    <section className="mf-access-card"><h2>With your Mac</h2>{choices.filter(({ key }) => ['system', 'computer', 'camera', 'audio'].includes(key)).map(renderChoice)}</section>
    <details className="mf-access-extra"><summary>Share camera previews with this browser</summary>{choices.filter(({ key }) => key === 'remote_preview').map(renderChoice)}</details>
    <p className="mf-access-note"><ShieldCheck size={17} />Changes apply to your Modulate across voice and all linked browsers. macOS permissions are still granted on your Mac.</p>
    <div className="mf-access-actions"><Button quiet disabled={Boolean(busy)} onClick={() => navigate('studio')}>Keep current access</Button><Button primary disabled={!online || Boolean(busy)} onClick={() => Object.keys(changed).length ? onSave(changed) : navigate('studio')}>{busy === 'access' ? 'Saving…' : 'Save & open Studio'}<ArrowRight size={16} /></Button></div>
  </EntryFrame>;
}
