'use client';
import React, { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Pause, Play, RotateCcw } from 'lucide-react';
import { Button } from '../ui';
import { checkApp } from './model';
import { idleInput } from '../../../shared/demo-runtime.mjs';
export function drawFrame(canvas, frame, audio) {
  const c = canvas?.getContext('2d');
  if (!c) return;
  for (const op of frame) {
    if (op.op === 'tone') {
      if (audio?.state === 'running') {
        const oscillator = audio.createOscillator(),
          gain = audio.createGain();
        oscillator.frequency.value = op.frequency;
        gain.gain.setValueAtTime(0.04, audio.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + op.duration);
        oscillator.connect(gain);
        gain.connect(audio.destination);
        oscillator.onended = () => {
          oscillator.disconnect();
          gain.disconnect();
        };
        oscillator.start();
        oscillator.stop(audio.currentTime + op.duration);
      }
      continue;
    }
    c.fillStyle = op.color;
    c.strokeStyle = op.color;
    c.lineWidth = 1;
    if (op.op === 'clear') c.fillRect(0, 0, 240, 135);
    if (op.op === 'rect') c.fillRect(op.x, op.y, op.w, op.h);
    if (op.op === 'circle') {
      c.beginPath();
      c.arc(op.x, op.y, op.r, 0, Math.PI * 2);
      c.fill();
    }
    if (op.op === 'line') {
      c.beginPath();
      c.moveTo(op.x, op.y);
      c.lineTo(op.x2, op.y2);
      c.stroke();
    }
    if (op.op === 'text') {
      c.font = `${op.size}px monospace`;
      c.textBaseline = 'top';
      c.fillText(op.text, op.x, op.y);
    }
  }
}
export default function VirtualDevice({ app, candidate, modules, busy, onReady, onReject }) {
  const canvas = useRef(null),
    worker = useRef(null),
    input = useRef(idleInput()),
    audio = useRef(null),
    callbacks = useRef({ onReady, onReject }),
    waiting = useRef(false),
    lastFrame = useRef([]);
  callbacks.current = { onReady, onReject };
  const [playing, setPlaying] = useState(false),
    [loaded, setLoaded] = useState(null),
    [failure, setFailure] = useState(''),
    [dial, setDial] = useState(0),
    [restart, setRestart] = useState(0);
  const target = candidate || app,
    error = checkApp(target, modules),
    revision = target?.id,
    attached = modules.join(',');
  const reset = () => {
    input.current = idleInput();
    setDial(0);
  };
  useEffect(() => {
    setPlaying(false);
    reset();
    waiting.current = false;
    if (!target || error) {
      if (candidate && error) callbacks.current.onReject(error);
      return;
    }
    let next,
      committed = false,
      cancelled = false,
      failed = false;
    const fail = (message) => {
      if (cancelled || failed) return;
      failed = true;
      setFailure(message);
      setPlaying(false);
      if (!committed) {
        next?.terminate();
        if (candidate) callbacks.current.onReject(message);
      } else {
        next?.terminate();
        setLoaded(null);
      }
    };
    const timeout = setTimeout(
      () => fail('The virtual device did not acknowledge the app in time.'),
      12000,
    );
    try {
      next = new Worker('/demo-runtime.js');
      next.onerror = () => fail('The restricted runtime could not start. Reload and try again.');
      next.onmessage = ({ data }) => {
        if (cancelled || failed || data.revision !== revision) return;
        if (data.type === 'error') {
          clearTimeout(timeout);
          fail(data.error);
          return;
        }
        if (data.type === 'ready') {
          clearTimeout(timeout);
          committed = true;
          worker.current?.terminate();
          worker.current = next;
          setLoaded(revision);
          setFailure('');
          lastFrame.current = data.frame;
          drawFrame(canvas.current, data.frame, null);
          if (candidate) callbacks.current.onReady(candidate);
        } else if (data.type === 'frame') {
          waiting.current = false;
          lastFrame.current = data.frame;
          drawFrame(canvas.current, data.frame, audio.current);
        }
      };
      next.postMessage({ type: 'stage', app: target, modules, revision });
    } catch {
      clearTimeout(timeout);
      fail('This browser could not create the isolated runtime.');
    }
    return () => {
      cancelled = true;
      clearTimeout(timeout);
      if (!committed) next?.terminate();
    };
    // An identity changes only on app activation/restart or a component change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revision, attached, restart]);
  useEffect(() => {
    const pause = () => {
      setPlaying(false);
      input.current = idleInput();
      audio.current?.suspend().catch(() => {});
    };
    const visibility = () => {
      if (document.hidden) pause();
    };
    window.addEventListener('blur', pause);
    document.addEventListener('visibilitychange', visibility);
    return () => {
      window.removeEventListener('blur', pause);
      document.removeEventListener('visibilitychange', visibility);
      worker.current?.terminate();
      audio.current?.close().catch(() => {});
    };
  }, []);
  const running = playing && !error && !busy && loaded === app?.id;
  useEffect(() => {
    if (!running) return;
    let last = performance.now(),
      sent = 0;
    const timer = setInterval(() => {
      const now = performance.now();
      if (waiting.current) {
        if (now - sent > 1000) {
          worker.current?.terminate();
          setFailure('The app stopped responding. Restart or restore your previous app.');
          setPlaying(false);
          setLoaded(null);
        }
        return;
      }
      sent = now;
      waiting.current = true;
      worker.current?.postMessage({
        type: 'frame',
        revision: app.id,
        input: input.current,
        dt: Math.min(0.05, (now - last) / 1000),
      });
      last = now;
    }, 33);
    return () => {
      clearInterval(timer);
      waiting.current = false;
    };
  }, [running, app?.id]);
  const togglePlay = async () => {
    if (!playing && modules.includes('speaker')) {
      try {
        const Audio = window.AudioContext || window.webkitAudioContext;
        if (Audio) {
          if (!audio.current) audio.current = new Audio();
          await audio.current.resume();
        }
      } catch {}
    }
    setPlaying((v) => !v);
  };
  const setControl = (kind, value) => {
    if (kind === 'x' || kind === 'y') input.current.joystick[kind] = value;
    else input.current[kind] = Boolean(value);
  };
  const hold = (kind, value) => ({
    onPointerDown: (e) => {
      e.currentTarget.setPointerCapture?.(e.pointerId);
      setControl(kind, value);
    },
    onPointerUp: () => setControl(kind, 0),
    onPointerCancel: () => setControl(kind, 0),
    onLostPointerCapture: () => setControl(kind, 0),
    onKeyDown: (e) => {
      if ([' ', 'Enter'].includes(e.key)) {
        e.preventDefault();
        setControl(kind, value);
      }
    },
    onKeyUp: () => setControl(kind, 0),
    onBlur: () => setControl(kind, 0),
  });
  const key = (event, down) => {
    if (['INPUT', 'BUTTON', 'A', 'TEXTAREA'].includes(event.target.tagName) || error || busy)
      return;
    const map = {
      ArrowLeft: ['x', -1],
      ArrowRight: ['x', 1],
      ArrowUp: ['y', -1],
      ArrowDown: ['y', 1],
      ' ': ['button_a', true],
      b: ['button_b', true],
    };
    const entry = map[event.key];
    if (!entry) return;
    if (!modules.includes(entry[0].startsWith('button') ? 'buttons' : 'joystick')) return;
    event.preventDefault();
    setControl(entry[0], down ? entry[1] : 0);
  };
  const disabled = !app || Boolean(error) || busy || loaded !== app?.id;
  return (
    <div className="md-device-area">
      <div
        className="md-device"
        tabIndex={0}
        aria-label="Virtual device. Arrow keys move, Space is A, B is B."
        onKeyDown={(e) => key(e, true)}
        onKeyUp={(e) => key(e, false)}
        onBlur={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget)) input.current = idleInput();
        }}
        style={{ '--app-color': '#a8b8ff' }}
      >
        <div className="md-device-label">
          <span>MODULATE / 01</span>
          <span>
            <i />
            VIRTUAL PI
          </span>
        </div>
        <div className="md-display">
          <canvas
            ref={canvas}
            width={240}
            height={135}
            role="img"
            aria-label={app ? `${app.title}: live generated app` : 'Empty virtual device'}
            style={{
              width: '100%',
              height: '100%',
              imageRendering: 'pixelated',
              background: '#080e1c',
            }}
          />
          {(!app || !modules.includes('display') || !running) && (
            <div className="md-screen-overlay">
              <strong>
                {!modules.includes('display')
                  ? 'Display disconnected'
                  : !app
                    ? 'What will you make?'
                    : busy
                      ? 'Creating your next app…'
                      : error
                        ? 'Waiting for a module'
                        : failure
                          ? 'App paused'
                          : loaded === app.id
                            ? 'Ready to play.'
                            : 'Checking app…'}
              </strong>
              <span>
                {!app ? 'Describe an idea below.' : 'Your generated code. Your controls.'}
              </span>
            </div>
          )}
        </div>
        <div className="md-device-footer">
          <span>240 × 135</span>
          <span>VIRTUAL HARDWARE</span>
          <span>● ●</span>
        </div>
        <div className="md-controls">
          <div className={`md-control-module ${modules.includes('joystick') ? '' : 'is-detached'}`}>
            <div
              className="md-joystick"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3,28px)',
                gap: 0,
                height: 'auto',
              }}
            >
              {[
                ['Up', 'y', -1, ArrowUp, 2],
                ['Left', 'x', -1, ArrowLeft, 1],
                ['Down', 'y', 1, ArrowDown, 2],
                ['Right', 'x', 1, ArrowRight, 3],
              ].map(([label, axis, value, Icon, col], i) => (
                <button
                  key={label}
                  style={{ gridColumn: col, gridRow: i === 0 ? 1 : 2 }}
                  aria-label={`Joystick ${label.toLowerCase()}`}
                  disabled={disabled || !modules.includes('joystick')}
                  {...hold(axis, value)}
                >
                  <Icon size={17} />
                </button>
              ))}
            </div>
            <span>JOYSTICK</span>
          </div>
          <div className={`md-control-module ${modules.includes('encoder') ? '' : 'is-detached'}`}>
            <div className="md-knob" style={{ transform: `rotate(${dial * 270 - 135}deg)` }}>
              <i />
            </div>
            <label className="mc-sr-only" htmlFor="demo-knob">
              Rotary knob
            </label>
            <input
              id="demo-knob"
              type="range"
              min="0"
              max="100"
              value={Math.round(dial * 100)}
              disabled={disabled || !modules.includes('encoder')}
              onChange={(e) => {
                const v = Number(e.target.value) / 100;
                setDial(v);
                input.current.encoder = v;
              }}
            />
            <span>ROTARY KNOB</span>
          </div>
          <div className={`md-control-module ${modules.includes('buttons') ? '' : 'is-detached'}`}>
            <div className="md-buttons">
              {['a', 'b'].map((b) => (
                <button
                  key={b}
                  aria-label={`Button ${b.toUpperCase()}`}
                  disabled={disabled || !modules.includes('buttons')}
                  {...hold(`button_${b}`, true)}
                >
                  {b.toUpperCase()}
                </button>
              ))}
            </div>
            <span>ACTION BUTTONS</span>
          </div>
        </div>
      </div>
      {(error || failure) && (
        <p className="md-hardware-error" role="status">
          {error || failure} Your saved app is kept.
        </p>
      )}
      <div className="md-playbar">
        <Button primary icon={running ? Pause : Play} disabled={disabled} onClick={togglePlay}>
          {running ? 'Pause' : 'Play app'}
        </Button>
        <Button
          quiet
          icon={RotateCcw}
          disabled={!app || busy || Boolean(error)}
          onClick={() => {
            setLoaded(null);
            setRestart((n) => n + 1);
          }}
        >
          Restart
        </Button>
        <span>{app ? 'Generated by Meta · runs locally' : 'No app loaded yet'}</span>
      </div>
      <p className="md-control-help">
        {app
          ? Object.entries(app.controls)
              .filter(([id]) => id !== 'display')
              .map(([id, text]) => `${MODULE_LABELS[id]}: ${text}`)
              .join(' · ')
          : 'Attach components, describe an idea, and Meta will write the app.'}
      </p>
    </div>
  );
}
const MODULE_LABELS = {
  joystick: 'Joystick',
  encoder: 'Knob',
  buttons: 'A / B',
  speaker: 'Speaker',
};
