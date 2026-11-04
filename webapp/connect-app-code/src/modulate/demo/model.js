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
    tag: 'I²C 0x20',
  },
  {
    id: 'encoder',
    name: 'Rotary knob',
    detail: 'Turn ideas up or down',
    symbol: '◉',
    tag: 'I²C 0x36',
  },
  {
    id: 'buttons',
    name: 'Action buttons',
    detail: 'Green A, red B',
    symbol: '●',
    tag: 'I²C 0x6E · 0x6F',
  },
  {
    id: 'imu',
    name: 'Motion sensor',
    detail: 'Tilt to steer or aim',
    symbol: '⟁',
    tag: 'I²C 0x6A',
  },
  {
    id: 'speaker',
    name: 'Speaker',
    detail: 'Little sounds, big character',
    symbol: '♪',
    tag: 'USB audio',
  },
  {
    id: 'camera',
    name: 'Camera',
    detail: 'Your webcam, kept in this tab',
    symbol: '◎',
    tag: 'Local video',
  },
];
// The paired computer is a host capability stored beside the Pi modules.
export const COMPUTER = 'computer';
export const DEFAULT_MODULES = ['display', 'joystick', 'encoder', 'buttons', 'imu', 'speaker', 'computer'];
// Scenes follow the order of the three-minute video.
export const SCENES = [
  ['Doom-style game', 'Hey Meta, make a game similar to old-school Doom.', 'device'],
  ['Update for new controls', 'Hey Meta, update the game with my new controls.', 'device'],
  ['Check my hardware', 'Hey Meta, check my hardware.', 'device'],
  ['Knob → Mac brightness', 'Control my Mac brightness with the knob.', 'muse'],
  ['Reverse the knob', 'Hey Meta, reverse the knob.', 'device'],
  ['Halloween mirror', 'Hey Meta, turn into a mirror and make it Halloween themed.', 'device'],
  ['Open the app library', 'Hey Meta, open the app library.', 'device'],
  ['Scroll with the joystick', 'Hey Meta, use the joystick to scroll the apps.', 'device'],
  ['Favorite the Doom game', 'Hey Meta, favorite the Doom game.', 'device'],
  ['Try something unsafe', 'Hey Meta, turn into an RFID badge cloner.', 'device'],
];
export function freshWorkspace() {
  return {
    version: 3,
    modules: [...DEFAULT_MODULES],
    apps: [],
    activeId: null,
    libraryControl: 'encoder',
    computer: { brightness: 70, volume: 40 },
    hardware: { imuDriver: 'ready', extraButton: null },
  };
}
const PART_NAMES = {
  display: 'the mini display',
  joystick: 'the joystick',
  encoder: 'the rotary knob',
  buttons: 'the action buttons',
  imu: 'the motion sensor',
  speaker: 'the speaker',
  camera: 'the camera',
  computer: 'a paired computer',
};
export function checkApp(app, modules) {
  if (!app) return null;
  try {
    validatePackage(app, modules);
    return null;
  } catch (e) {
    // Name missing parts the way the component tray does.
    const missing = app.requires?.filter?.((m) => !modules.includes(m)) || [];
    if (missing.length && /^Attach /.test(e.message))
      return `Attach ${missing.map((m) => PART_NAMES[m] || m).join(' and ')} to run this app.`;
    return e.message;
  }
}
const level = (value, fallback) =>
  Number.isInteger(value) && value >= 0 && value <= 100 ? value : fallback;
export function restoreWorkspace(raw) {
  try {
    const w = JSON.parse(raw);
    if (
      ![2, 3].includes(w?.version) ||
      !Array.isArray(w.apps) ||
      w.apps.length > 24 ||
      !Array.isArray(w.modules)
    )
      return freshWorkspace();
    const known = [...MODULES.map((m) => m.id), COMPUTER];
    const apps = w.apps
      .filter(
        (a) =>
          a &&
          /^[a-f0-9]{64}$/.test(a.id) &&
          !checkApp(a, known) &&
          a.inference?.model === 'muse-spark-1.3',
      )
      .map((a) => ({ ...a, favorite: a.favorite === true, trashed: a.trashed === true }));
    const fresh = freshWorkspace();
    const extra = w.hardware?.extraButton;
    return {
      version: 3,
      // Version 2 predates the motion sensor and paired computer; attach them once.
      modules: [
        ...new Set([
          ...w.modules.filter((m) => known.includes(m)),
          ...(w.version === 2 ? ['imu', COMPUTER] : []),
        ]),
      ],
      apps,
      activeId: apps.some((a) => a.id === w.activeId && !a.trashed)
        ? w.activeId
        : apps.find((a) => !a.trashed)?.id || null,
      libraryControl: w.libraryControl === 'joystick' ? 'joystick' : 'encoder',
      computer: {
        brightness: level(w.computer?.brightness, fresh.computer.brightness),
        volume: level(w.computer?.volume, fresh.computer.volume),
      },
      hardware: {
        imuDriver: w.hardware?.imuDriver === 'missing' ? 'missing' : 'ready',
        extraButton:
          extra && ['0x6f', '0x6d'].includes(extra.address) ? { address: extra.address } : null,
      },
    };
  } catch {
    return freshWorkspace();
  }
}
// Components the runtime can use right now: a sensor without its driver is not ready.
export function readyModules(workspace) {
  return workspace.modules.filter(
    (m) => m !== 'imu' || workspace.hardware.imuDriver === 'ready',
  );
}
export const hasConflict = (workspace) =>
  workspace.modules.includes('buttons') && workspace.hardware.extraButton?.address === '0x6f';
export function hardwareReport(workspace, repair = null) {
  const on = (m) => workspace.modules.includes(m);
  const conflict = hasConflict(workspace);
  const bus = [];
  if (on('joystick')) bus.push({ address: '0x20', device: 'Qwiic joystick', status: 'ok' });
  if (on('encoder')) bus.push({ address: '0x36', device: 'Rotary encoder', status: 'ok' });
  if (on('imu'))
    bus.push({
      address: '0x6a',
      device: 'LSM6DS3TR-C IMU (WHO_AM_I 0x6A)',
      status:
        workspace.hardware.imuDriver === 'ready' ? 'driver ready' : 'chip detected; driver missing',
    });
  if (on('buttons')) {
    bus.push({ address: '0x6e', device: 'Qwiic Button, green (A)', status: 'ok' });
    bus.push({
      address: '0x6f',
      device: 'Qwiic Button, red (B)',
      status: conflict
        ? 'inconsistent reads; B presses flicker; another board may answer here'
        : 'ok',
    });
    if (workspace.hardware.extraButton?.address === '0x6d')
      bus.push({ address: '0x6d', device: 'Qwiic Button, new', status: 'ok' });
  }
  return {
    bus,
    imu: {
      attached: on('imu'),
      driver: on('imu') ? workspace.hardware.imuDriver : 'none',
    },
    conflict,
    repair,
  };
}
// Library order on the device: favorites first, then newest.
export function libraryList(apps) {
  const live = apps.filter((a) => !a.trashed).reverse();
  return [...live.filter((a) => a.favorite), ...live.filter((a) => !a.favorite)];
}
export const contract = (app) =>
  app.kind === 'controls'
    ? {
        kind: 'controls',
        title: app.title,
        description: app.description,
        requires: app.requires,
        controls: app.controls,
        bindings: app.bindings,
      }
    : {
        title: app.title,
        description: app.description,
        requires: app.requires,
        controls: app.controls,
        code: app.code,
      };
