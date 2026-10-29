import React from 'react';
import { AudioLines } from 'lucide-react';

export function Button({ children, icon: Icon, primary, danger, quiet, className = '', ...props }) {
  return <button className={`mc-button ${primary ? 'mc-primary' : ''} ${danger ? 'mc-danger' : ''} ${quiet ? 'mc-quiet' : ''} ${className}`} {...props}>{Icon && <Icon size={16} aria-hidden="true" />}{children}</button>;
}
export function Badge({ children, live, warning }) {
  return <span className={`mc-badge ${live ? 'is-live' : ''} ${warning ? 'is-warning' : ''}`}><span className="mc-dot" />{children}</span>;
}
export function Toggle({ label, checked, disabled, onChange }) {
  return <button className={`mc-toggle ${checked ? 'is-on' : ''}`} type="button" role="switch" aria-label={label} aria-checked={Boolean(checked)} disabled={disabled} onClick={() => onChange(!checked)}><span /></button>;
}
export function Card({ children, className = '', ...props }) {
  return <section className={`mc-card ${className}`} {...props}>{children}</section>;
}
export function Brand({ small }) {
  return <span className={`mc-brand ${small ? 'mc-brand-small' : ''}`}><img className="mc-mark" src="/brand/modulate-cube.png" width="44" height="44" alt="" aria-hidden="true" />modulate<span className="mc-brand-period">.</span></span>;
}
export function GadgetIllustration() {
  return <div className="mc-gadget-art" aria-hidden="true">
    <div className="mc-orbit mc-orbit-one" /><div className="mc-orbit mc-orbit-two" />
    <span className="mc-art-spark mc-art-spark-one">+</span><span className="mc-art-spark mc-art-spark-two">+</span>
    <div className="mc-art-wire mc-art-wire-one" /><div className="mc-art-wire mc-art-wire-two" />
    <div className="mc-art-knob"><div /><span /></div>
    <div className="mc-art-device"><div className="mc-art-device-top"><span>MODULATE</span><span>01</span></div><div className="mc-art-screen"><AudioLines size={48} strokeWidth={1.3} /><span>Hey Meta.</span></div><div className="mc-art-device-bottom"><i /><span /><span /></div></div>
    <div className="mc-art-button"><i /></div><div className="mc-art-caption"><span className="mc-dot" />One device. Your next idea.</div>
  </div>;
}

