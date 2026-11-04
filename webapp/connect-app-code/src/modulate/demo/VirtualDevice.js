'use client';
import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Pause,
  Play,
  RotateCcw,
  RotateCw,
  Smartphone,
} from 'lucide-react';
import { Button } from '../ui';
import { checkApp } from './model';
import { applyBinding, idleInput, verifyPackage } from '../../../shared/demo-runtime.mjs';

const clamp = (v, lo = -1, hi = 1) => Math.max(lo, Math.min(hi, v));
// Capture can throw for a pointer that is no longer active; input must still register.
const capture = (e) => {
  try {
    e.currentTarget.setPointerCapture?.(e.pointerId);
  } catch {}
};
// Palette effects run on downsampled local pixels; nothing leaves the tab.
function tint(data, palette) {
  for (let i = 0; i < data.length; i += 4) {
    const r = data[i],
      g = data[i + 1],
      b = data[i + 2];
    if (palette === 'mono') {
      const y = 0.3 * r + 0.59 * g + 0.11 * b;
      data[i] = data[i + 1] = data[i + 2] = y;
    } else if (palette === 'neon') {
      data[i] = (r - 128) * 1.7 + 150;
      data[i + 1] = (g - 128) * 1.5 + 110;
      data[i + 2] = (b - 128) * 1.9 + 175;
    } else if (palette === 'warm') {
      data[i] = r * 1.12 + 22;
      data[i + 1] = g * 0.98 + 6;
      data[i + 2] = b * 0.72;
    }
  }
}
function drawCamera(c, op, camera) {
  const video = camera?.video;
  if (!video || video.readyState < 2 || !video.videoWidth) {
    c.fillStyle = '#1b2230';
    c.fillRect(op.x, op.y, op.w, op.h);
    c.fillStyle = '#8fa3b8';
    c.font = '9px monospace';
    c.textBaseline = 'top';
    c.fillText(camera?.label || 'Camera starts on Play', op.x + 6, op.y + 6);
    return;
  }
  const pw = Math.max(1, Math.round(op.w / op.pixelate)),
    ph = Math.max(1, Math.round(op.h / op.pixelate));
  const off = camera.scratch || (camera.scratch = document.createElement('canvas'));
  off.width = pw;
  off.height = ph;
  const o = off.getContext('2d', { willReadFrequently: true });
  // Cover-fit the camera image into the requested rectangle.
  const scale = Math.max(pw / video.videoWidth, ph / video.videoHeight);
  const sw = pw / scale,
    sh = ph / scale;
  o.save();
  if (op.mirror) {
    o.translate(pw, 0);
    o.scale(-1, 1);
  }
  o.drawImage(
    video,
    (video.videoWidth - sw) / 2,
    (video.videoHeight - sh) / 2,
    sw,
    sh,
    0,
    0,
    pw,
    ph,
  );
  o.restore();
  if (op.palette !== 'natural') {
    const image = o.getImageData(0, 0, pw, ph);
    tint(image.data, op.palette);
    o.putImageData(image, 0, 0);
  }
  c.imageSmoothingEnabled = false;
  c.drawImage(off, 0, 0, pw, ph, op.x, op.y, op.w, op.h);
}
export function drawFrame(canvas, frame, audio, camera) {
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
    if (op.op === 'camera') {
      drawCamera(c, op, camera);
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
const CONTROL_NAMES = {
  encoder: 'KNOB',
  joystick_x: 'STICK ←→',
  joystick_y: 'STICK ↑↓',
  button_a: 'BUTTON A',
  button_b: 'BUTTON B',
};
// Trusted host screens: the control mapping status and the on-device library.
function drawControls(canvas, app, computer) {
  const c = canvas?.getContext('2d');
  if (!c || !c.fillText) return;
  c.fillStyle = '#0a1220';
  c.fillRect(0, 0, 240, 135);
  c.textBaseline = 'top';
  c.fillStyle = '#7fd8ff';
  c.font = '8px monospace';
  c.fillText('CONTROL MAPPING · PAIRED MAC', 8, 7);
  c.fillStyle = '#eef6ff';
  c.font = '11px monospace';
  c.fillText(app.title.slice(0, 32), 8, 19);
  app.bindings.forEach((b, i) => {
    const key = b.target.split('.')[1];
    const y = 40 + i * 30;
    c.fillStyle = '#9fb3c8';
    c.font = '8px monospace';
    c.fillText(
      `${CONTROL_NAMES[b.control]} → ${key.toUpperCase()}  ${b.step > 0 ? '+' : ''}${b.step}/step`,
      8,
      y,
    );
    c.fillStyle = '#1d2a3a';
    c.fillRect(8, y + 12, 190, 9);
    c.fillStyle = key === 'brightness' ? '#ffd166' : '#7be6af';
    c.fillRect(8, y + 12, (190 * (computer?.[key] ?? 0)) / 100, 9);
    c.fillStyle = '#eef6ff';
    c.fillText(`${computer?.[key] ?? 0}%`, 204, y + 12);
  });
  c.fillStyle = '#5f7489';
  c.font = '7px monospace';
  c.fillText('Runs locally · no model call per turn', 8, 124);
}
function drawLibrary(canvas, library) {
  const c = canvas?.getContext('2d');
  if (!c || !c.fillText) return;
  const { entries, selected, control } = library;
  c.fillStyle = '#0b1020';
  c.fillRect(0, 0, 240, 135);
  c.textBaseline = 'top';
  c.fillStyle = '#c7b8ff';
  c.font = '8px monospace';
  c.fillText(`APP LIBRARY · ${entries.length} SAVED`, 8, 7);
  if (!entries.length) {
    c.fillStyle = '#9fb3c8';
    c.font = '10px monospace';
    c.fillText('Nothing saved yet.', 8, 50);
  }
  const first = Math.max(0, Math.min(selected - 2, entries.length - 5));
  entries.slice(first, first + 5).forEach((entry, i) => {
    const index = first + i,
      y = 22 + i * 19;
    if (index === selected) {
      c.fillStyle = '#2b2f63';
      c.fillRect(4, y - 3, 232, 17);
      c.fillStyle = '#9d8cff';
      c.fillRect(4, y - 3, 3, 17);
    }
    c.fillStyle = entry.favorite ? '#ffd166' : '#3d4a5f';
    c.font = '10px monospace';
    c.fillText(entry.favorite ? '★' : '☆', 12, y);
    c.fillStyle = index === selected ? '#ffffff' : '#b9c6d6';
    c.fillText(entry.title.slice(0, 28), 26, y);
  });
  c.fillStyle = '#6f7f95';
  c.font = '7px monospace';
  c.fillText(
    `${control === 'joystick' ? 'JOYSTICK' : 'KNOB'}: SCROLL · A: OPEN · B: ★`,
    8,
    124,
  );
}
const DETENT_DEGREES = 18;
export default function VirtualDevice({
  app,
  candidate,
  modules,
  busy,
  onReady,
  onReject,
  computer = null,
  onComputer = () => {},
  library = null,
  onLibrary = () => {},
  imuState = 'ready',
  conflict = false,
  say = '',
}) {
  const canvas = useRef(null),
    worker = useRef(null),
    input = useRef(idleInput()),
    audio = useRef(null),
    camera = useRef({ video: null, stream: null, scratch: null, label: '' }),
    video = useRef(null),
    callbacks = useRef({}),
    waiting = useRef(false),
    knobDrag = useRef(null),
    tiltPad = useRef(null),
    motion = useRef(null),
    lastFrame = useRef(null),
    heldSince = useRef(0);
  callbacks.current = { onReady, onReject, onComputer, onLibrary };
  const [playing, setPlaying] = useState(false),
    [loaded, setLoaded] = useState(null),
    [failure, setFailure] = useState(''),
    [dial, setDial] = useState(0),
    [angle, setAngle] = useState(0),
    [puck, setPuck] = useState({ x: 0, y: 0 }),
    [cameraState, setCameraState] = useState('off'),
    [motionOn, setMotionOn] = useState(false),
    [canMotion, setCanMotion] = useState(false),
    [restart, setRestart] = useState(0);
  const target = candidate || app,
    missingDriver = imuState === 'missing' && target?.requires?.includes('imu'),
    error = missingDriver
      ? 'The motion sensor’s driver is missing. Ask Modulate to check your hardware.'
      : checkApp(target, modules),
    revision = target?.id,
    attached = modules.join(',');
  const controlsApp = app?.kind === 'controls' && loaded === app.id;
  const libraryOpen = Boolean(library?.open);
  const live = useRef({});
  live.current = { app, computer, controlsApp, library, libraryOpen, conflict };
  const needsCamera = Boolean(
    app && app.kind !== 'controls' && app.requires.includes('camera') && modules.includes('camera'),
  );
  const reset = () => {
    input.current = idleInput();
    setDial(0);
    setPuck({ x: 0, y: 0 });
  };
  const stopCamera = () => {
    camera.current.stream?.getTracks().forEach((t) => t.stop());
    camera.current.stream = null;
    if (video.current) video.current.srcObject = null;
    setCameraState('off');
  };
  useEffect(() => {
    setPlaying(false);
    reset();
    waiting.current = false;
    if (!target || error) {
      if (candidate && error) callbacks.current.onReject(error);
      return;
    }
    if (target.kind === 'controls') {
      // A declarative mapping has no code: the trusted verifier checks it directly.
      try {
        verifyPackage(null, target, modules);
        worker.current?.terminate();
        worker.current = null;
        setLoaded(revision);
        setFailure('');
        if (candidate) callbacks.current.onReady(candidate);
      } catch (e) {
        if (candidate) callbacks.current.onReject(e.message);
      }
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
          if (!live.current.libraryOpen) drawFrame(canvas.current, data.frame, null, camera.current);
          if (candidate) callbacks.current.onReady(candidate);
        } else if (data.type === 'frame') {
          waiting.current = false;
          lastFrame.current = data.frame;
          if (!live.current.libraryOpen)
            drawFrame(canvas.current, data.frame, audio.current, camera.current);
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
    // Only touch devices offer phone-motion tilt; decided after hydration.
    setCanMotion('DeviceOrientationEvent' in window && navigator.maxTouchPoints > 0);
    const pause = () => {
      setPlaying(false);
      input.current = idleInput();
      setPuck({ x: 0, y: 0 });
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
      camera.current.stream?.getTracks().forEach((t) => t.stop());
      if (motion.current) window.removeEventListener('deviceorientation', motion.current);
    };
  }, []);
  // Release the camera whenever the running app no longer needs it.
  useEffect(() => {
    if (!needsCamera || !playing) stopCamera();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsCamera, playing, app?.id]);
  useEffect(() => {
    if (libraryOpen) {
      setPlaying(false);
      drawLibrary(canvas.current, library);
    } else if (controlsApp) drawControls(canvas.current, app, computer);
    else if (lastFrame.current && loaded === app?.id)
      drawFrame(canvas.current, lastFrame.current, null, camera.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [libraryOpen, library, controlsApp, app, computer]);
  const running = playing && !error && !busy && loaded === app?.id && !controlsApp && !libraryOpen;
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
  // Held joystick repeats for the library menu and joystick bindings.
  useEffect(() => {
    if (!libraryOpen && !controlsApp) return;
    const timer = setInterval(() => {
      const { joystick } = input.current;
      const { library: menu, controlsApp: mapping, app: current, computer: levels } = live.current;
      // The press itself moved once; repeat only while the stick stays held.
      if (menu?.open && menu.control === 'joystick') {
        if (Math.abs(joystick.y) > 0.5 && performance.now() - heldSince.current > 400)
          callbacks.current.onLibrary({ type: 'move', delta: Math.sign(joystick.y) });
      } else if (mapping && levels) {
        let next = levels;
        for (const b of current.bindings) {
          if (b.control === 'joystick_x' && Math.abs(joystick.x) > 0.5)
            next = applyBinding(next, b, Math.sign(joystick.x));
          if (b.control === 'joystick_y' && Math.abs(joystick.y) > 0.5)
            next = applyBinding(next, b, -Math.sign(joystick.y));
        }
        if (next !== levels) callbacks.current.onComputer(next);
      }
    }, 180);
    return () => clearInterval(timer);
  }, [libraryOpen, controlsApp]);
  const startCamera = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      camera.current.label = 'Camera unavailable here';
      setCameraState('blocked');
      return;
    }
    setCameraState('starting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { width: { ideal: 320 }, height: { ideal: 180 }, facingMode: 'user' },
      });
      camera.current.stream = stream;
      camera.current.video = video.current;
      video.current.srcObject = stream;
      await video.current.play().catch(() => {});
      setCameraState('on');
    } catch {
      camera.current.label = 'Camera blocked: allow it to see yourself';
      setCameraState('blocked');
    }
  };
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
    if (!playing && needsCamera && cameraState !== 'on') startCamera();
    setPlaying((v) => !v);
  };
  const press = (kind) => {
    const { library: menu, controlsApp: mapping, app: current, computer: levels, conflict: busB } =
      live.current;
    if (kind === 'button_b' && busB) return false;
    if (menu?.open) {
      callbacks.current.onLibrary({ type: kind === 'button_a' ? 'launch' : 'favorite' });
      return false;
    }
    if (mapping && levels) {
      let next = levels;
      for (const b of current.bindings) if (b.control === kind) next = applyBinding(next, b, 1);
      if (next !== levels) callbacks.current.onComputer(next);
      return false;
    }
    return true;
  };
  const setControl = (kind, value) => {
    if (kind === 'y' && value && !input.current.joystick.y) {
      heldSince.current = performance.now();
      const menu = live.current.library;
      if (menu?.open && menu.control === 'joystick')
        callbacks.current.onLibrary({ type: 'move', delta: Math.sign(value) });
    }
    if (kind === 'x' || kind === 'y') input.current.joystick[kind] = value;
    else if (!value) input.current[kind] = false;
    else if (press(kind)) input.current[kind] = true;
  };
  const turn = (delta) => {
    const { library: menu, controlsApp: mapping, app: current, computer: levels } = live.current;
    setAngle((a) => a + delta * DETENT_DEGREES);
    const position = clamp(input.current.encoder + delta / 24, 0, 1);
    input.current.encoder = position;
    setDial(position);
    if (menu?.open) {
      if (menu.control === 'encoder') callbacks.current.onLibrary({ type: 'move', delta });
      return;
    }
    if (mapping && levels) {
      let next = levels;
      for (const b of current.bindings) if (b.control === 'encoder') next = applyBinding(next, b, delta);
      if (next !== levels) callbacks.current.onComputer(next);
    }
  };
  const hold = (kind, value) => ({
    onPointerDown: (e) => {
      capture(e);
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
  const knobAngle = (e) => {
    const box = e.currentTarget.getBoundingClientRect();
    return (
      (Math.atan2(e.clientY - box.top - box.height / 2, e.clientX - box.left - box.width / 2) *
        180) /
      Math.PI
    );
  };
  const knobEvents = {
    onPointerDown: (e) => {
      if (!knobReady) return;
      capture(e);
      knobDrag.current = { angle: knobAngle(e), rest: 0 };
    },
    onPointerMove: (e) => {
      if (!knobDrag.current) return;
      const now = knobAngle(e);
      let delta = now - knobDrag.current.angle;
      if (delta > 180) delta -= 360;
      if (delta < -180) delta += 360;
      knobDrag.current.angle = now;
      knobDrag.current.rest += delta;
      const detents = Math.trunc(knobDrag.current.rest / DETENT_DEGREES);
      if (detents) {
        knobDrag.current.rest -= detents * DETENT_DEGREES;
        turn(detents);
      }
    },
    onPointerUp: () => (knobDrag.current = null),
    onPointerCancel: () => (knobDrag.current = null),
    onWheel: (e) => {
      if (knobReady && e.deltaY) turn(e.deltaY < 0 ? 1 : -1);
    },
    onKeyDown: (e) => {
      const delta = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
      if (delta && knobReady) {
        e.preventDefault();
        e.stopPropagation();
        turn(delta);
      }
    },
  };
  const setTilt = (x, y) => {
    const next = { x: clamp(x), y: clamp(y) };
    input.current.tilt = next;
    setPuck(next);
  };
  const tiltEvents = {
    onPointerDown: (e) => {
      if (!tiltReady) return;
      capture(e);
      tiltPad.current = e.currentTarget.getBoundingClientRect();
      tiltEvents.onPointerMove(e);
    },
    onPointerMove: (e) => {
      const box = tiltPad.current;
      if (!box) return;
      setTilt(
        (e.clientX - box.left - box.width / 2) / (box.width / 2),
        (e.clientY - box.top - box.height / 2) / (box.height / 2),
      );
    },
    onPointerUp: () => {
      tiltPad.current = null;
      setTilt(0, 0);
    },
    onPointerCancel: () => {
      tiltPad.current = null;
      setTilt(0, 0);
    },
  };
  const toggleMotion = async () => {
    if (motion.current) {
      window.removeEventListener('deviceorientation', motion.current);
      motion.current = null;
      setMotionOn(false);
      setTilt(0, 0);
      return;
    }
    try {
      if (typeof DeviceOrientationEvent?.requestPermission === 'function')
        if ((await DeviceOrientationEvent.requestPermission()) !== 'granted') return;
    } catch {
      return;
    }
    let base = null;
    motion.current = (event) => {
      if (event.beta === null || event.gamma === null) return;
      base ||= { beta: event.beta, gamma: event.gamma };
      setTilt((event.gamma - base.gamma) / 30, (event.beta - base.beta) / 30);
    };
    window.addEventListener('deviceorientation', motion.current);
    setMotionOn(true);
  };
  const key = (event, down) => {
    if (['INPUT', 'BUTTON', 'A', 'TEXTAREA'].includes(event.target.tagName) || busy) return;
    const map = {
      ArrowLeft: ['x', -1],
      ArrowRight: ['x', 1],
      ArrowUp: ['y', -1],
      ArrowDown: ['y', 1],
      ' ': ['button_a', true],
      b: ['button_b', true],
    };
    const tiltKeys = { a: [-1, 0], d: [1, 0], w: [0, -1], s: [0, 1] };
    if (tiltKeys[event.key] && tiltReady) {
      event.preventDefault();
      const [x, y] = tiltKeys[event.key];
      if (down) setTilt(x || input.current.tilt.x, y || input.current.tilt.y);
      else setTilt(x ? 0 : input.current.tilt.x, y ? 0 : input.current.tilt.y);
      return;
    }
    if (event.key === '[' || event.key === ']') {
      if (down && knobReady) turn(event.key === ']' ? 1 : -1);
      return;
    }
    const entry = map[event.key];
    if (!entry) return;
    if (!modules.includes(entry[0].startsWith('button') ? 'buttons' : 'joystick')) return;
    if (event.repeat && entry[0].startsWith('button')) return;
    event.preventDefault();
    setControl(entry[0], down ? entry[1] : 0);
  };
  const appDisabled = !app || Boolean(error) || busy || loaded !== app?.id;
  // Menus and mappings take input without Play; games take it while running.
  const inputReady = (m) => modules.includes(m) && !busy && (libraryOpen || !appDisabled);
  const knobReady = inputReady('encoder'),
    tiltReady = inputReady('imu');
  const help = libraryOpen
    ? 'Library: scroll with the ' +
      (library.control === 'joystick' ? 'joystick' : 'knob') +
      ' · A opens · B favorites'
    : app?.kind === 'controls'
      ? Object.values(app.controls).join(' · ')
      : app
        ? Object.entries(app.controls)
            .filter(([id]) => id !== 'display' && id !== 'computer')
            .map(([id, text]) => `${MODULE_LABELS[id] || id}: ${text}`)
            .join(' · ')
      : 'Attach components, describe an idea, and Meta will write the app.';
  return (
    <div className="md-device-area">
      <div
        className="md-device"
        tabIndex={0}
        aria-label="Virtual device. Arrow keys: joystick. W A S D: tilt. [ and ]: knob. Space: A. B: B."
        onKeyDown={(e) => key(e, true)}
        onKeyUp={(e) => key(e, false)}
        onBlur={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget)) {
            input.current = { ...idleInput(), encoder: input.current.encoder };
            setPuck({ x: 0, y: 0 });
          }
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
        {say && (
          <p className="md-say" role="status" aria-live="polite">
            <span aria-hidden="true" />“{say}”
          </p>
        )}
        <div className="md-display">
          <canvas
            ref={canvas}
            width={240}
            height={135}
            role="img"
            aria-label={
              libraryOpen
                ? 'App library on the device screen'
                : app
                  ? `${app.title}: ${app.kind === 'controls' ? 'control mapping' : 'live generated app'}`
                  : 'Empty virtual device'
            }
            style={{
              width: '100%',
              height: '100%',
              imageRendering: 'pixelated',
              background: '#080e1c',
            }}
          />
          {!libraryOpen && (!app || !modules.includes('display') || (!running && !controlsApp)) && (
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
                {!app
                  ? 'Describe an idea below.'
                  : error
                    ? error
                    : cameraState === 'blocked'
                      ? camera.current.label
                      : 'Your generated code. Your controls.'}
              </span>
            </div>
          )}
          <video ref={video} className="md-camera-source" muted playsInline aria-hidden="true" />
        </div>
        <div className="md-device-footer">
          <span>240 × 135</span>
          <span>
            {cameraState === 'on'
              ? 'CAMERA LIVE · STAYS IN THIS TAB'
              : conflict
                ? 'I²C 0x6F: TWO BOARDS ANSWER'
                : 'VIRTUAL HARDWARE'}
          </span>
          <span>● ●</span>
        </div>
        <div className="md-controls">
          <div className={`md-control-module ${modules.includes('joystick') ? '' : 'is-detached'}`}>
            <div className="md-joystick md-dpad">
              {[
                ['Up', 'y', -1, ArrowUp, 2],
                ['Left', 'x', -1, ArrowLeft, 1],
                ['Down', 'y', 1, ArrowDown, 2],
                ['Right', 'x', 1, ArrowRight, 3],
              ].map(([label, axis, value, Icon, col], i) => (
                <button
                  key={label}
                  type="button"
                  style={{ gridColumn: col, gridRow: i === 0 ? 1 : 2 }}
                  aria-label={`Joystick ${label.toLowerCase()}`}
                  disabled={!inputReady('joystick')}
                  {...hold(axis, value)}
                >
                  <Icon size={16} />
                </button>
              ))}
            </div>
            <span>JOYSTICK</span>
          </div>
          <div className={`md-control-module ${modules.includes('encoder') ? '' : 'is-detached'}`}>
            <div className="md-knob-row">
              <button
                type="button"
                className="md-knob-step"
                aria-label="Turn knob left"
                disabled={!knobReady}
                onClick={() => turn(-1)}
              >
                <RotateCcw size={12} />
              </button>
              <div
                className="md-knob"
                role="slider"
                tabIndex={knobReady ? 0 : -1}
                aria-label="Rotary knob"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(dial * 100)}
                aria-disabled={!knobReady}
                style={{ transform: `rotate(${angle}deg)` }}
                {...knobEvents}
              >
                <i />
              </div>
              <button
                type="button"
                className="md-knob-step"
                aria-label="Turn knob right"
                disabled={!knobReady}
                onClick={() => turn(1)}
              >
                <RotateCw size={12} />
              </button>
            </div>
            <span>ROTARY KNOB</span>
          </div>
          <div
            className={`md-control-module ${modules.includes('imu') || imuState === 'missing' ? '' : 'is-detached'}`}
          >
            <div
              className={`md-tilt ${tiltReady ? '' : 'is-off'}`}
              role="application"
              aria-label="Tilt pad: drag to tilt the device"
              {...tiltEvents}
            >
              <i style={{ transform: `translate(${puck.x * 17}px, ${puck.y * 17}px)` }} />
            </div>
            <span>
              {imuState === 'missing' ? 'IMU · NO DRIVER' : 'TILT'}
              {canMotion && tiltReady && (
                <button
                  type="button"
                  className={`md-motion ${motionOn ? 'is-on' : ''}`}
                  aria-label={motionOn ? 'Stop using phone motion' : 'Use phone motion for tilt'}
                  onClick={toggleMotion}
                >
                  <Smartphone size={10} />
                </button>
              )}
            </span>
          </div>
          <div className={`md-control-module ${modules.includes('buttons') ? '' : 'is-detached'}`}>
            <div className="md-buttons">
              {['a', 'b'].map((b) => (
                <button
                  key={b}
                  type="button"
                  aria-label={`Button ${b.toUpperCase()}`}
                  className={b === 'b' && conflict ? 'is-flaky' : ''}
                  disabled={!inputReady('buttons')}
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
      {(error || failure) && !libraryOpen && (
        <p className="md-hardware-error" role="status">
          {error || failure} Your saved app is kept.
        </p>
      )}
      <div className="md-playbar">
        {controlsApp && !libraryOpen ? (
          <span className="md-live-pill">Mapping active · turn the knob</span>
        ) : (
          <Button
            primary
            icon={running ? Pause : Play}
            disabled={appDisabled || libraryOpen || controlsApp}
            onClick={togglePlay}
          >
            {running ? 'Pause' : 'Play app'}
          </Button>
        )}
        <Button
          quiet
          icon={RotateCcw}
          disabled={!app || busy || Boolean(error) || libraryOpen}
          onClick={() => {
            setLoaded(null);
            setRestart((n) => n + 1);
          }}
        >
          Restart
        </Button>
        <span>
          {libraryOpen
            ? 'Library open on the device'
            : app
              ? app.kind === 'controls'
                ? 'Mapping by Meta · runs locally'
                : 'Generated by Meta · runs locally'
              : 'No app loaded yet'}
        </span>
      </div>
      <p className="md-control-help">{help}</p>
    </div>
  );
}
const MODULE_LABELS = {
  joystick: 'Joystick',
  encoder: 'Knob',
  buttons: 'A / B',
  speaker: 'Speaker',
  imu: 'Tilt',
  camera: 'Camera',
};
