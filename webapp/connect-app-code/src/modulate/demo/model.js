// Browser-only examples. Nothing in this module calls the agent or host bridge.
export const STORAGE_KEY = 'modulate.playground.v1';
export const COLORS = { blue: '#42c5ff', pink: '#f88bc1', yellow: '#f0eb5b', green: '#7be6af' };
export const MODULES = [
  { id: 'display', name: 'Mini display', detail: '240 × 135 · game output', tag: 'SPI', symbol: '▣' },
  { id: 'joystick', name: 'Joystick', detail: 'Move left and right', tag: '0x20', symbol: '✥' },
  { id: 'encoder', name: 'Rotary knob', detail: 'Steer or tune a note', tag: '0x36', symbol: '◉' },
  { id: 'buttons', name: 'A + B buttons', detail: 'Boost, play, and pause', tag: '0x6E / 0x6F', symbol: '● ●' },
  { id: 'speaker', name: 'Speaker', detail: 'Play a note in your browser', tag: 'USB', symbol: '≋' },
];
export const RECIPES = [
  { id: 'orbit', title: 'Orbit Catch', kind: 'orbit', color: 'blue', speed: 1, description: 'Catch falling stars. Find your orbit.', prompt: 'Make a game where I catch stars', label: 'Catch stars' },
  { id: 'rally', title: 'Pixel Rally', kind: 'rally', color: 'pink', speed: 1, description: 'Dodge the traffic. Take the fast lane.', prompt: 'Make a little racing game', label: 'Race a kart' },
  { id: 'synth', title: 'Pocket Synth', kind: 'synth', color: 'green', speed: 1, description: 'Turn the knob. Find your sound.', prompt: 'Turn this into a synthesizer', label: 'Make music' },
];
const validApp = app => app && typeof app.id === 'string' && /^[a-z0-9-]{1,60}$/.test(app.id) && typeof app.title === 'string' && app.title.length > 0 && app.title.length <= 60 && RECIPES.some(r => r.kind === app.kind) && Object.hasOwn(COLORS, app.color) && [0.7, 1, 1.5].includes(app.speed);
export const freshWorkspace = () => ({ version: 1, modules: MODULES.map(m => m.id), apps: RECIPES.map(({ id, title, kind, color, speed }) => ({ id, title, kind, color, speed })), activeId: 'orbit' });
export function restoreWorkspace(raw) {
  try {
    if (typeof raw !== 'string' || raw.length > 20000) return freshWorkspace();
    const value = JSON.parse(raw);
    if (value.version !== 1 || !Array.isArray(value.modules) || !Array.isArray(value.apps) || !value.apps.length || value.apps.length > 24 || !value.apps.every(validApp)) return freshWorkspace();
    if (new Set(value.apps.map(a => a.id)).size !== value.apps.length || !value.apps.some(a => a.id === value.activeId)) return freshWorkspace();
    return { version: 1, modules: MODULES.filter(m => value.modules.includes(m.id)).map(m => m.id), apps: value.apps.map(({ id, title, kind, color, speed }) => ({ id, title, kind, color, speed })), activeId: value.activeId };
  } catch { return freshWorkspace(); }
}
export function checkApp(app, modules) {
  if (!validApp(app)) return 'This demo app is invalid. Choose an example from the library.';
  if (!modules.includes('display')) return 'Attach the mini display to see this app.';
  if (app.kind === 'synth' && !modules.includes('speaker')) return 'Attach the speaker to play this synth.';
  if (app.kind === 'synth' && !modules.includes('encoder')) return 'Attach the rotary knob to tune this synth.';
  if (app.kind !== 'synth' && !modules.some(m => ['joystick', 'encoder'].includes(m))) return 'Attach a joystick or rotary knob to steer.';
  return '';
}
export function interpretRequest(text, current) {
  const lower = text.toLowerCase().trim();
  const recipe = /\b(rac\w*|kart|car|driv\w*)\b/.test(lower) ? RECIPES[1] : /\b(synth\w*|music|instrument)\b/.test(lower) ? RECIPES[2] : /\b(star\w*|catch|orbit|space)\b/.test(lower) ? RECIPES[0] : null;
  const color = Object.keys(COLORS).find(c => new RegExp(`\\b${c}\\b`).test(lower));
  const speed = /\b(faster|fast|harder)\b/.test(lower) ? 1.5 : /\b(slower|slow|easier)\b/.test(lower) ? 0.7 : null;
  if (!recipe && !color && !speed) return null;
  const base = recipe || current;
  return { title: base.title, kind: base.kind, color: color || base.color, speed: speed || base.speed };
}
export const newGame = () => ({ x: 120, elapsed: 0, score: 0, lives: 3, objects: [], spawn: 0, serial: 0 });
export function stepGame(previous, dt, direction, app, boost = false) {
  if (previous.lives <= 0 || app.kind === 'synth') return previous;
  const game = { ...previous, objects: [], elapsed: previous.elapsed + dt, spawn: previous.spawn + dt, x: Math.max(26, Math.min(214, previous.x + direction * dt * 125)) };
  const velocity = (app.kind === 'rally' ? 55 : 39) * app.speed * (boost ? 1.6 : 1);
  for (const object of previous.objects) {
    const next = { ...object, y: object.y + velocity * dt };
    if (next.y >= 108 && object.y < 108) {
      const hit = Math.abs(next.x - game.x) < 18;
      if (app.kind === 'orbit') { if (hit) game.score += 10; else game.lives = Math.max(0, game.lives - 1); }
      else { if (hit) game.lives = Math.max(0, game.lives - 1); else game.score += 10; }
    }
    if (next.y < 140) game.objects.push(next);
  }
  if (game.spawn > 0.95 / app.speed) {
    game.serial += 1;
    game.objects.push({ id: game.serial, x: 40 + (game.serial * 71 % 160), y: -8 });
    game.spawn = 0;
  }
  return game;
}
