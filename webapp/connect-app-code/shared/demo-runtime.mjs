// Generated code executes only inside QuickJS/WASM, with no host callbacks or module loader.
// "computer" is the virtual paired computer; it is a host capability, not a Pi peripheral.
export const MODULE_IDS = [
  'display',
  'joystick',
  'encoder',
  'buttons',
  'speaker',
  'imu',
  'camera',
  'computer',
];
export const CONTROL_INPUTS = {
  encoder: 'encoder',
  joystick_x: 'joystick',
  joystick_y: 'joystick',
  button_a: 'buttons',
  button_b: 'buttons',
};
export const CONTROL_TARGETS = ['computer.brightness', 'computer.volume'];
export const CAMERA_PALETTES = ['natural', 'mono', 'neon', 'warm'];
const text = (value, max, empty = false) =>
  typeof value === 'string' && value.length <= max && (empty || Boolean(value.trim()));
function validateControls(app) {
  if (
    !Array.isArray(app.bindings) ||
    app.bindings.length < 1 ||
    app.bindings.length > 4 ||
    'code' in app
  )
    throw Error('A control mapping needs 1–4 bindings and no code.');
  const seen = new Set();
  for (const b of app.bindings) {
    if (
      !b ||
      typeof b !== 'object' ||
      Object.keys(b).some((k) => !['control', 'target', 'step'].includes(k)) ||
      !CONTROL_INPUTS[b.control] ||
      !CONTROL_TARGETS.includes(b.target) ||
      !Number.isInteger(b.step) ||
      b.step === 0 ||
      Math.abs(b.step) > 10
    )
      throw Error('Invalid control binding.');
    if (seen.has(b.control)) throw Error('Each control can have only one binding.');
    seen.add(b.control);
    if (!app.requires.includes(CONTROL_INPUTS[b.control]))
      throw Error(`List ${CONTROL_INPUTS[b.control]} in requires to bind ${b.control}.`);
  }
  if (!app.requires.includes('computer')) throw Error('Pair a computer to map controls to it.');
}
export function validatePackage(app, modules = MODULE_IDS) {
  if (!app || typeof app !== 'object' || Array.isArray(app)) throw Error('Invalid app package.');
  const kind = app.kind ?? 'app';
  if (
    !['app', 'controls'].includes(kind) ||
    !text(app.title, 80) ||
    !text(app.description, 400, true) ||
    (kind === 'app' &&
      (typeof app.code !== 'string' || app.code.length < 20 || app.code.length > 40000)) ||
    (app.say !== undefined && !text(app.say, 200, true))
  )
    throw Error('Invalid title, description or source size.');
  if (
    !Array.isArray(app.requires) ||
    !app.requires.includes('display') ||
    new Set(app.requires).size !== app.requires.length ||
    app.requires.some((m) => !MODULE_IDS.includes(m))
  )
    throw Error('Invalid required components.');
  const missing = app.requires.filter((m) => !modules.includes(m));
  if (missing.length) throw Error(`Attach ${missing.join(', ')} to run this app.`);
  if (!app.controls || typeof app.controls !== 'object' || Array.isArray(app.controls))
    throw Error('controls must be an object of short strings.');
  for (const [k, v] of Object.entries(app.controls)) {
    // Precise messages let the reviewer repair the right field.
    if (!app.requires.includes(k))
      throw Error(`controls.${k.slice(0, 30)} names a component missing from requires.`);
    if (typeof v !== 'string' || v.length > 160)
      throw Error(`controls.${k} must be a string of at most 160 characters.`);
  }
  if (kind === 'controls') validateControls(app);
  return app;
}
// Copy only the supported contract; never forward model metadata as trusted evidence.
export function contractOf(app) {
  const base = {
    title: app.title,
    description: app.description,
    requires: app.requires,
    controls: app.controls,
    ...(typeof app.say === 'string' ? { say: app.say } : {}),
  };
  return app.kind === 'controls'
    ? {
        kind: 'controls',
        ...base,
        bindings: app.bindings.map(({ control, target, step }) => ({ control, target, step })),
      }
    : { ...base, code: app.code };
}
const color = (value) => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
const number = (value) =>
  typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= 4096;
export function validateFrame(frame, modules) {
  if (!Array.isArray(frame) || frame.length < 1) throw Error('draw must return a command array.');
  if (frame.length > 160)
    throw Error(`A frame had ${frame.length} drawing commands; the limit is 160.`);
  if (frame[0]?.op !== 'clear') throw Error('Each frame must begin with {op:"clear"}.');
  let tones = 0,
    cameras = 0;
  for (const c of frame) {
    if (!c || typeof c !== 'object') throw Error('Invalid drawing command.');
    const fields = {
      clear: [],
      rect: ['x', 'y', 'w', 'h'],
      circle: ['x', 'y', 'r'],
      line: ['x', 'y', 'x2', 'y2'],
      text: ['x', 'y', 'size'],
    }[c.op];
    if (c.op === 'tone') {
      if (
        !modules.includes('speaker') ||
        ++tones > 1 ||
        !number(c.frequency) ||
        c.frequency < 50 ||
        c.frequency > 2000 ||
        !number(c.duration) ||
        c.duration < 0.01 ||
        c.duration > 0.12
      )
        throw Error('Invalid audio command.');
    } else if (c.op === 'camera') {
      // The host paints local camera pixels here; generated code never receives them.
      if (
        !modules.includes('camera') ||
        ++cameras > 1 ||
        ['x', 'y', 'w', 'h'].some((k) => !number(c[k])) ||
        c.w < 1 ||
        c.h < 1 ||
        typeof c.mirror !== 'boolean' ||
        !Number.isInteger(c.pixelate) ||
        c.pixelate < 1 ||
        c.pixelate > 16 ||
        !CAMERA_PALETTES.includes(c.palette)
      )
        throw Error('Invalid camera command.');
    } else if (
      !fields ||
      !color(c.color) ||
      fields.some((k) => !number(c[k])) ||
      (c.op === 'text' &&
        (typeof c.text !== 'string' || c.text.length > 160 || c.size < 4 || c.size > 32)) ||
      (c.op === 'rect' && (c.w < 0 || c.h < 0)) ||
      (c.op === 'circle' && c.r < 0)
    )
      throw Error('Invalid drawing command.');
  }
  return frame;
}
export const idleInput = () => ({
  joystick: { x: 0, y: 0 },
  encoder: 0,
  button_a: false,
  button_b: false,
  tilt: { x: 0, y: 0 },
});
export function createMachine(QuickJS, app, modules) {
  validatePackage(app, modules);
  if (app.kind === 'controls') throw Error('Control mappings have no code to run.');
  const rt = QuickJS.newRuntime();
  rt.setMemoryLimit(16 * 1024 * 1024);
  rt.setMaxStackSize(256 * 1024);
  let deadline = Date.now() + 150;
  rt.setInterruptHandler(() => Date.now() > deadline);
  const vm = rt.newContext();
  let dispatch,
    disposed = false;
  const lines = app.code.split('\n');
  // Point repairs at the generated line; the wrapper adds three lines before the code.
  const locate = (error) => {
    const match = /generated-app\.js:(\d+)(?::(\d+))?/.exec(error?.stack || '');
    const line = (match ? Number(match[1]) : error?.lineNumber) - 3;
    if (!Number.isInteger(line) || line < 1 || line > lines.length) return '';
    const column = match?.[2] ? `, column ${match[2]}` : '';
    return ` (app code line ${line}${column}: ${lines[line - 1].trim().slice(0, 120)})`;
  };
  const unwrap = (result) => {
    if (result.error) {
      const error = vm.dump(result.error);
      result.error.dispose();
      const message = `${error?.message || 'Runtime rejected the app'}${locate(error)}`;
      throw Error(String(message).slice(0, 300));
    }
    return result.value;
  };
  try {
    dispatch = unwrap(
      vm.evalCode(
        `(function(){
      const encode=JSON.stringify, decode=JSON.parse;
      const app=(function(){"use strict";\n${app.code}\n;return {init,update,draw};})();
      let state=app.init();
      return function(input,dt){
        if(input!==null) state=app.update(state,decode(input),dt);
        if(encode(state).length>32768) throw Error('State too large');
        return encode(app.draw(state));
      };
    })()`,
        'generated-app.js',
      ),
    );
  } catch (e) {
    vm.dispose();
    rt.dispose();
    throw e;
  }
  return {
    frame(input = null, dt = 1 / 30) {
      if (disposed) throw Error('Runtime closed');
      deadline = Date.now() + 40;
      const arg = input === null ? vm.null : vm.newString(JSON.stringify(input));
      const delta = vm.newNumber(Math.min(0.05, Math.max(0, dt)));
      let handle;
      try {
        handle = unwrap(vm.callFunction(dispatch, vm.undefined, arg, delta));
        if (vm.typeof(handle) !== 'string') throw Error('Drawing output must be JSON.');
        const text = vm.getString(handle);
        if (text.length > 40000) throw Error('Frame too large.');
        return validateFrame(JSON.parse(text), modules);
      } finally {
        handle?.dispose();
        if (input !== null) arg.dispose();
        delta.dispose();
      }
    },
    close() {
      if (!disposed) {
        disposed = true;
        dispatch.dispose();
        vm.dispose();
        rt.dispose();
      }
    },
  };
}
// Apply one physical detent or press locally; no model call is involved.
export function applyBinding(levels, binding, detents = 1) {
  const key = binding.target.split('.')[1];
  const next = Math.max(0, Math.min(100, levels[key] + binding.step * detents));
  return { ...levels, [key]: next };
}
function verifyControls(app) {
  let levels = { brightness: 50, volume: 50 };
  for (let i = 0; i < 150; i++)
    for (const binding of app.bindings)
      levels = applyBinding(levels, binding, i % 2 ? 1 : -1);
  if (Object.values(levels).some((v) => !Number.isInteger(v) || v < 0 || v > 100))
    throw Error('Binding produced an out-of-range setting.');
  return {
    passed: true,
    frames: 0,
    distinctFrames: 0,
    checks: [
      'control mapping contract',
      'controls and paired-computer targets attached',
      'bounded steps',
      '150 simulated detents in both directions',
    ],
  };
}
export function verifyPackage(QuickJS, app, modules) {
  validatePackage(app, modules);
  if (app.kind === 'controls') return verifyControls(app);
  const machine = createMachine(QuickJS, app, modules);
  let count = 0;
  const signatures = new Set();
  try {
    signatures.add(JSON.stringify(machine.frame()));
    for (let i = 0; i < 150; i++) {
      const input = idleInput();
      if (modules.includes('joystick')) input.joystick = { x: Math.sin(i / 8), y: Math.cos(i / 8) };
      if (modules.includes('encoder')) input.encoder = (i % 101) / 100;
      if (modules.includes('buttons')) {
        input.button_a = i % 30 < 3;
        input.button_b = i % 51 < 2;
      }
      if (modules.includes('imu')) input.tilt = { x: Math.sin(i / 11), y: Math.cos(i / 13) };
      signatures.add(JSON.stringify(machine.frame(input)));
      count++;
    }
    return {
      passed: true,
      frames: count + 1,
      distinctFrames: signatures.size,
      checks: [
        'package and component contract',
        'isolated initialization',
        '150 input frames',
        'bounded state, drawing, camera and audio',
      ],
    };
  } finally {
    machine.close();
  }
}
