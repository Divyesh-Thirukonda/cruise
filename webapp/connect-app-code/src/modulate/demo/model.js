import { validatePackage } from '../../../shared/demo-runtime.mjs';
export const STORAGE_KEY = 'modulate.playground.live.v2';
export const MODULES = [
  {
    id: 'display',
    name: 'Mini display',
    detail: '240 × 135 color pixels',
    symbol: '▣',
    tag: 'SPI display',
  },
  {
    id: 'joystick',
    name: 'Joystick',
    detail: 'Move in two dimensions',
    symbol: '✥',
    tag: 'Analog input',
  },
  {
    id: 'encoder',
    name: 'Rotary knob',
    detail: 'Turn ideas up or down',
    symbol: '◉',
    tag: 'Rotary input',
  },
  {
    id: 'buttons',
    name: 'Action buttons',
    detail: 'Two buttons. Any purpose.',
    symbol: '●',
    tag: 'Digital inputs',
  },
  {
    id: 'speaker',
    name: 'Speaker',
    detail: 'Little sounds, big character',
    symbol: '♪',
    tag: 'Audio output',
  },
];
export const SUGGESTIONS = [
  [
    'Meteor garden',
    'Make a game where I grow glowing flowers by catching meteors with the joystick. A plants a seed and the knob changes the sky color.',
  ],
  [
    'Pocket sequencer',
    'Build a colorful step sequencer. The knob chooses the tempo, A adds a note, B changes the melody, and the speaker plays it.',
  ],
  [
    'Tiny aquarium',
    'Make an interactive aquarium. The joystick moves a fish, A drops food, B changes its color, and the knob changes the current.',
  ],
];
export function freshWorkspace() {
  return { version: 2, modules: MODULES.map((m) => m.id), apps: [], activeId: null };
}
export function checkApp(app, modules) {
  if (!app) return null;
  try {
    validatePackage(app, modules);
    return null;
  } catch (e) {
    return e.message;
  }
}
export function restoreWorkspace(raw) {
  try {
    const w = JSON.parse(raw);
    if (
      w?.version !== 2 ||
      !Array.isArray(w.apps) ||
      w.apps.length > 24 ||
      !Array.isArray(w.modules)
    )
      return freshWorkspace();
    const apps = w.apps.filter(
      (a) =>
        a &&
        /^[a-f0-9]{64}$/.test(a.id) &&
        !checkApp(
          a,
          MODULES.map((m) => m.id),
        ) &&
        a.inference?.model === 'muse-spark-1.3',
    );
    return {
      version: 2,
      modules: [...new Set(w.modules.filter((m) => MODULES.some((x) => x.id === m)))],
      apps,
      activeId: apps.some((a) => a.id === w.activeId) ? w.activeId : apps[0]?.id || null,
    };
  } catch {
    return freshWorkspace();
  }
}
