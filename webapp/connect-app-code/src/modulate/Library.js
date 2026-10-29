import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, Gamepad2, Library, Monitor, Play, RotateCcw, Star, Trash2 } from 'lucide-react';

const dateMs = value => typeof value === 'number' ? (value < 1e12 ? value * 1000 : value) : Date.parse(value);

export default function AppLibrary({ library, disabled, running, deviceConnected, now, onAction }) {
  const [tab, setTab] = useState('all');
  const [prepared, setPrepared] = useState(null);
  const [dismissed, setDismissed] = useState(null);
  const dialogRef = useRef(null);
  const catalog = library?.items ?? library?.entries;
  const entries = Array.isArray(catalog) ? catalog : [];
  const menuOpen = library?.view?.open ?? library?.open;
  const changingDisabled = disabled || running || Boolean(library?.error);
  const pending = library && Object.prototype.hasOwnProperty.call(library, 'purge_confirmation') ? library.purge_confirmation : prepared;
  const confirmation = pending?.id && pending.id !== dismissed ? pending : null;
  const confirmationId = confirmation?.id;
  const currentEntry = confirmation && entries.find(entry => entry.id === confirmation.entry_id);
  const expires = dateMs(confirmation?.expires_at);
  const expired = !Number.isFinite(expires) || expires <= now;
  const visible = entries.filter(entry => tab === 'trash' ? entry.trashed : !entry.trashed && (tab !== 'favorites' || entry.favorite));

  const perform = (action, entry, extra = {}, success) => onAction('library', '/api/library', { action, ...(entry ? { entry_id: entry.id } : {}), ...extra }, success);
  const cancelPurge = async () => {
    if (disabled || !confirmation) return;
    const id = confirmation.id;
    if (await perform('cancel_purge', null, { confirmation_id: id })) { setDismissed(id); setPrepared(null); }
  };
  const preparePurge = async entry => {
    const result = await perform('purge', entry);
    const next = result?.library?.purge_confirmation || result?.purge_confirmation;
    if (next) { setPrepared(next); setDismissed(null); }
  };
  const confirmPurge = async () => {
    if (!confirmation || expired || currentEntry?.protected || changingDisabled) return;
    const id = confirmation.id;
    const result = await perform('confirm_purge', { id: confirmation.entry_id }, { confirmation_id: id }, 'App permanently deleted.');
    if (result) { setDismissed(id); setPrepared(null); }
  };

  useEffect(() => {
    if (!confirmationId) return;
    const previous = document.activeElement;
    dialogRef.current?.querySelector('button')?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, [confirmationId]);

  return <>
    {library?.error && <p className="mc-notice mc-notice-error" role="status">{String(library.error)}</p>}
    <section className="mc-card mc-library-intro">
      <div className="mc-library-symbol"><Library size={25} /></div>
      <div><h2>Your ideas, ready to return to.</h2><p>Say “Hey Meta, open my app library.” Open, favorite or delete by voice. Connected controls can navigate the menu too.</p><span>Saved on your companion · moving an app to Trash keeps its running version on the device.</span></div>
      <button className="mc-button" disabled={disabled || !deviceConnected || (!menuOpen && changingDisabled)} onClick={() => perform(menuOpen ? 'close' : 'open', null, { tab })}><Monitor size={16} />{menuOpen ? 'Return to app' : 'Show on device'}<ArrowRight size={15} /></button>
    </section>
    <div className="mc-library-toolbar"><div className="mc-segmented" role="group" aria-label="Library filter">{[['all', 'All apps'], ['favorites', 'Favorites'], ['trash', 'Trash']].map(([key, label]) => <button key={key} aria-pressed={tab === key} className={tab === key ? 'is-selected' : ''} onClick={() => setTab(key)}>{label}<span>{entries.filter(entry => key === 'trash' ? entry.trashed : !entry.trashed && (key !== 'favorites' || entry.favorite)).length}</span></button>)}</div><span>{visible.length} {visible.length === 1 ? 'app' : 'apps'}</span></div>
    {visible.length ? <div className="mc-library-grid">{visible.map(entry => <article className="mc-card mc-library-entry" key={entry.id} aria-label={entry.title}>
      <div className="mc-library-entry-top"><span className="mc-library-app-icon">{entry.kind === 'game' ? <Gamepad2 size={25} /> : <Monitor size={25} />}</span>{entry.active && <span className="mc-badge is-live"><span className="mc-dot" />Running</span>}{!entry.trashed && <button className={`mc-library-star ${entry.favorite ? 'is-favorite' : ''}`} disabled={changingDisabled} aria-label={`${entry.favorite ? 'Unfavorite' : 'Favorite'} ${entry.title}`} aria-pressed={Boolean(entry.favorite)} onClick={() => perform('favorite', entry, { favorite: !entry.favorite })}><Star size={21} fill={entry.favorite ? 'currentColor' : 'none'} /></button>}</div>
      <h2>{entry.title || 'Untitled app'}</h2><p>{entry.kind === 'game' ? 'Game' : entry.kind === 'control' ? 'Controller' : 'App'}<span>·</span><code>{String(entry.id).slice(0, 8)}</code></p>
      <div className="mc-library-entry-actions">{entry.trashed ? <><button className="mc-button" disabled={changingDisabled} onClick={() => perform('restore', entry, {}, 'App restored to your library.')}><RotateCcw size={15} />Restore</button><button className="mc-button mc-quiet mc-danger" disabled={changingDisabled || entry.protected} title={entry.protected ? 'Running and recovery versions cannot be permanently deleted.' : undefined} onClick={() => preparePurge(entry)}><Trash2 size={15} />Delete forever</button></> : <><button className="mc-button mc-primary" disabled={changingDisabled || !deviceConnected} onClick={() => perform('launch', entry)}><Play size={15} />Open</button><button className="mc-button mc-quiet" aria-label={`Move ${entry.title} to Trash`} disabled={changingDisabled} onClick={() => perform('trash', entry, {}, 'Moved to Trash. The current running app is unchanged.')}><Trash2 size={15} />Move to Trash</button></>}</div>
      {entry.trashed && entry.protected && <p className="mc-library-protected">Kept while running or available for recovery.</p>}
    </article>)}</div> : <section className="mc-card mc-empty mc-library-empty"><Library size={32} /><strong>{tab === 'trash' ? 'Trash is empty' : tab === 'favorites' ? 'Keep your favorites close' : 'Your next idea starts the collection'}</strong><p>{tab === 'trash' ? 'Deleted apps stay here until you restore or permanently delete them.' : tab === 'favorites' ? 'Say “Hey Meta, favorite this app,” or tap a star.' : 'Successfully activated apps appear here automatically.'}</p></section>}
    {confirmation && <div className="mc-modal-backdrop"><section className="mc-modal" role="alertdialog" aria-modal="true" aria-labelledby="mc-purge-title" aria-describedby="mc-purge-description" ref={dialogRef} onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); cancelPurge(); }
      if (event.key === 'Tab') {
        const buttons = dialogRef.current?.querySelectorAll('button:not([disabled])');
        if (!buttons?.length) { event.preventDefault(); return; }
        const first = buttons[0], last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    }}><span className="mc-eyebrow">PERMANENT DELETE</span><h2 id="mc-purge-title">Delete “{confirmation.title}” forever?</h2><p id="mc-purge-description">This removes this saved version from your library and Trash. You cannot restore it afterward.</p>{expired && <p className="mc-inline-error">This confirmation expired. Cancel and try again.</p>}{currentEntry?.protected && <p className="mc-inline-error">This version is now needed for running or recovery.</p>}<div className="mc-library-confirm-actions"><button className="mc-button" disabled={disabled} onClick={cancelPurge}>Keep in Trash</button><button className="mc-button mc-danger" disabled={changingDisabled || expired || !currentEntry || currentEntry.protected} onClick={confirmPurge}>Permanently delete</button></div></section></div>}
  </>;
}
