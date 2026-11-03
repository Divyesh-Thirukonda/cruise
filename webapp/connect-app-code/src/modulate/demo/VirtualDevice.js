'use client';

import React, { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Pause, Play, RotateCcw, Volume2 } from 'lucide-react';
import { Button } from '../ui';
import { checkApp, COLORS, newGame, stepGame } from './model';

export default function VirtualDevice({ app, modules, busy }) {
  const [game, setGame] = useState(newGame);
  const [playing, setPlaying] = useState(false);
  const [dial, setDial] = useState(50);
  const [sound, setSound] = useState('Sound starts when you press Play note.');
  const controls = useRef({ direction: 0, boost: false, target: null });
  const audio = useRef(null);
  const error = checkApp(app, modules);
  const running = playing && !error && !busy && game.lives > 0;
  const color = COLORS[app.color];
  const resetControls = () => { controls.current = { direction: 0, boost: false, target: null }; };

  useEffect(() => {
    if (error || busy) { setPlaying(false); resetControls(); audio.current?.suspend().catch(() => {}); }
  }, [error, busy]);
  useEffect(() => {
    const pause = () => { resetControls(); setPlaying(false); };
    const visibility = () => { if (document.hidden) pause(); };
    window.addEventListener('blur', pause);
    document.addEventListener('visibilitychange', visibility);
    return () => { window.removeEventListener('blur', pause); document.removeEventListener('visibilitychange', visibility); audio.current?.close().catch(() => {}); };
  }, []);
  useEffect(() => {
    if (!running || app.kind === 'synth') return;
    let frame;
    let last = 0;
    const tick = time => {
      if (time - last >= 32) {
        const dt = last ? Math.min((time - last) / 1000, 0.05) : 0;
        last = time;
        setGame(previous => {
          const { direction, target, boost } = controls.current;
          const movement = target === null ? direction : Math.max(-1, Math.min(1, (target - previous.x) / 8));
          return stepGame(previous, dt, movement, app, boost && modules.includes('buttons'));
        });
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [running, app, modules]);

  const steer = direction => { controls.current.target = null; controls.current.direction = direction; };
  const restart = () => { resetControls(); setGame(newGame()); setPlaying(true); };
  const note = async () => {
    if (error || busy) return;
    try {
      const Audio = window.AudioContext || window.webkitAudioContext;
      if (!Audio) { setSound('This browser cannot play audio. Try a game from the library.'); return; }
      if (!audio.current) audio.current = new Audio();
      const context = audio.current;
      await context.resume();
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = 'triangle';
      oscillator.frequency.value = 130.81 * 2 ** (dial / 50);
      gain.gain.setValueAtTime(0, context.currentTime);
      gain.gain.linearRampToValueAtTime(0.12, context.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.4);
      oscillator.connect(gain); gain.connect(context.destination);
      oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
      oscillator.start(); oscillator.stop(context.currentTime + 0.42);
      setSound(`Played ${Math.round(oscillator.frequency.value)} Hz through browser audio.`);
    } catch { setSound('Audio is unavailable. Check your browser’s sound setting.'); }
  };
  const key = (event, down) => {
    if (['INPUT', 'TEXTAREA', 'BUTTON', 'A'].includes(event.target.tagName) || error || busy) return;
    const k = event.key.toLowerCase();
    if (['arrowleft', 'arrowright', 'a', 'd'].includes(k) && modules.includes('joystick')) {
      event.preventDefault(); steer(down ? (['arrowleft', 'a'].includes(k) ? -1 : 1) : 0);
    }
    if (k === ' ' && modules.includes('buttons')) {
      event.preventDefault(); controls.current.boost = down;
      if (down && !event.repeat && app.kind === 'synth') note();
    }
  };
  const hold = direction => ({
    onPointerDown: event => { event.currentTarget.setPointerCapture?.(event.pointerId); steer(direction); },
    onPointerUp: () => steer(0), onPointerCancel: () => steer(0), onLostPointerCapture: () => steer(0),
    onKeyDown: event => { if ([' ', 'Enter'].includes(event.key)) { event.preventDefault(); steer(direction); } },
    onKeyUp: event => { if ([' ', 'Enter'].includes(event.key)) steer(0); }, onBlur: () => steer(0),
  });
  return <div className="md-device-area">
    <div className="md-device" tabIndex={0} aria-label="Virtual device. Arrow keys steer, space boosts. Focus here to use the keyboard." onKeyDown={e => key(e, true)} onKeyUp={e => key(e, false)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) resetControls(); }} style={{ '--app-color': color }}>
      <div className="md-device-label"><span>MODULATE / 01</span><span><i />VIRTUAL PI</span></div>
      <div className="md-display">
        {modules.includes('display') ? <svg viewBox="0 0 240 135" role="img" aria-label={`${app.title}. Score ${game.score}. ${game.lives} lives.`}>
          <rect width="240" height="135" fill={app.kind === 'rally' ? '#0c1722' : '#080e1c'} />
          {app.kind === 'orbit' && <>{Array.from({ length: 26 }, (_, i) => <rect key={i} x={(i * 43 + 11) % 240} y={(i * 29 + game.elapsed * 4) % 135} width={i % 4 ? 1 : 2} height={i % 4 ? 1 : 2} fill={i % 4 ? '#49617c' : '#a8bfd5'} />)}<circle cx="190" cy="38" r="22" fill="#162948" /><ellipse cx="190" cy="38" rx="35" ry="8" fill="none" stroke="#314d76" strokeWidth="3" transform="rotate(-25 190 38)" /></>}
          {app.kind === 'rally' && <><rect x="22" y="0" width="196" height="135" fill="#1b2935" /><path d="M22 0V135 M218 0V135" stroke={color} strokeWidth="2" />{[86, 154].map(x => <path key={x} d={`M${x} -30V170`} stroke="#69818e" strokeWidth="1" strokeDasharray="12 12" strokeDashoffset={-game.elapsed * app.speed * 55 % 24} />)}</>}
          {app.kind !== 'synth' && <>
            {game.objects.map(object => app.kind === 'orbit' ? <path key={object.id} d="M0 -6 2 -2 6 0 2 2 0 6 -2 2 -6 0 -2 -2Z" transform={`translate(${object.x} ${object.y})`} fill="#f0eb5b" /> : <g key={object.id} transform={`translate(${object.x} ${object.y})`}><rect x="-7" y="-10" width="14" height="20" rx="3" fill="#f0b777" /><rect x="-5" y="-5" width="10" height="5" fill="#334453" /></g>)}
            <g transform={`translate(${game.x} 112)`}>{app.kind === 'orbit' ? <><path d="M0 -10 11 6 5 3 -5 3 -11 6Z" fill={color} /><path d="M-3 5 0 11 3 5" fill="#f0b777" /></> : <><rect x="-8" y="-11" width="16" height="22" rx="3" fill={color} /><rect x="-5" y="-6" width="10" height="6" fill="#183049" /><path d="M-10 -6V0 M10 -6V0 M-10 6V10 M10 6V10" stroke="#05080e" strokeWidth="3" /></>}</g>
            <rect x="0" y="0" width="240" height="17" fill="#080e1ce6" /><text x="8" y="11" fill="#e1efff" fontSize="6" fontFamily="monospace">{app.kind === 'orbit' ? 'ORBIT CATCH' : 'PIXEL RALLY'}</text><text x="232" y="11" fill={color} fontSize="6" textAnchor="end" fontFamily="monospace">{String(game.score).padStart(4, '0')} / {'♥'.repeat(game.lives)}</text>
          </>}
          {app.kind === 'synth' && <><text x="120" y="28" fill={color} fontSize="8" textAnchor="middle" fontFamily="monospace">POCKET SYNTH</text><polyline fill="none" stroke={color} strokeWidth="2" points={Array.from({ length: 120 }, (_, i) => `${i * 2},${67 + Math.sin(i * (0.1 + dial / 300)) * 21}`).join(' ')} /><text x="120" y="115" fill="#c6d3e5" fontSize="8" textAnchor="middle" fontFamily="monospace">{Math.round(130.81 * 2 ** (dial / 50))} Hz · TRIANGLE</text></>}
        </svg> : <div className="md-no-display">Display disconnected</div>}
        {modules.includes('display') && app.kind !== 'synth' && !running && <div className="md-screen-overlay"><strong>{game.lives <= 0 ? `${game.score} points. Again?` : error ? 'Waiting for a module' : busy ? 'Preparing example…' : playing ? 'Paused' : 'Ready when you are.'}</strong><span>{game.lives <= 0 ? 'Hit restart for another run.' : 'Connect. Create. Play.'}</span></div>}
      </div>
      <div className="md-device-footer"><span>240 × 135</span><span>SOFTWARE SIMULATION</span><span>● ●</span></div>
      <div className="md-controls">
        <div className={`md-control-module ${modules.includes('joystick') ? '' : 'is-detached'}`}><div className="md-joystick"><button type="button" aria-label="Steer left" disabled={!modules.includes('joystick') || Boolean(error) || busy} {...hold(-1)}><ArrowLeft size={19} /></button><i /><button type="button" aria-label="Steer right" disabled={!modules.includes('joystick') || Boolean(error) || busy} {...hold(1)}><ArrowRight size={19} /></button></div><span>JOYSTICK</span></div>
        <div className={`md-control-module ${modules.includes('encoder') ? '' : 'is-detached'}`}><div className="md-knob" style={{ transform: `rotate(${dial * 2.7 - 135}deg)` }}><i /></div><label className="mc-sr-only" htmlFor="demo-knob">Rotary knob</label><input id="demo-knob" type="range" min="0" max="100" value={dial} disabled={!modules.includes('encoder') || Boolean(error) || busy} onChange={event => { const value = Number(event.target.value); setDial(value); controls.current.target = 26 + value * 1.88; }} /><span>ROTARY KNOB</span></div>
        <div className={`md-control-module ${modules.includes('buttons') ? '' : 'is-detached'}`}><div className="md-buttons"><button type="button" aria-label={app.kind === 'synth' ? 'Button A: play note' : 'Button A: hold to boost'} disabled={!modules.includes('buttons') || Boolean(error) || busy} onClick={app.kind === 'synth' ? note : undefined} onPointerDown={e => { e.currentTarget.setPointerCapture?.(e.pointerId); controls.current.boost = true; }} onPointerUp={() => { controls.current.boost = false; }} onPointerCancel={() => { controls.current.boost = false; }} onLostPointerCapture={() => { controls.current.boost = false; }} onKeyDown={e => { if ([' ', 'Enter'].includes(e.key)) controls.current.boost = true; }} onKeyUp={() => { controls.current.boost = false; }} onBlur={() => { controls.current.boost = false; }}>A</button><button type="button" aria-label="Button B: pause" disabled={!modules.includes('buttons') || busy} onClick={() => { setPlaying(false); resetControls(); if (app.kind === 'synth') { audio.current?.suspend().catch(() => {}); setSound('Sound paused. Press Play note to resume.'); } }}>B</button></div><span>ACTION BUTTONS</span></div>
      </div>
    </div>
    {error && <p className="md-hardware-error" role="status">{error} Your saved app is kept.</p>}
    <div className="md-playbar">{app.kind === 'synth' ? <Button primary icon={Volume2} disabled={Boolean(error) || busy} onClick={note}>Play note</Button> : <><Button primary icon={running ? Pause : Play} disabled={Boolean(error) || busy} onClick={() => game.lives <= 0 ? restart() : setPlaying(!running)}>{running ? 'Pause' : game.lives <= 0 ? 'Play again' : 'Play game'}</Button><Button quiet icon={RotateCcw} disabled={Boolean(error) || busy} onClick={restart}>Restart</Button><output aria-label="Game score">{game.score} points · {game.lives} lives</output></>}</div>
    <p className="md-control-help">{app.kind === 'synth' ? sound : 'Hold the joystick arrows or drag the knob to steer. A boosts, B pauses. Click the device to use ← → and Space.'}</p>
  </div>;
}
