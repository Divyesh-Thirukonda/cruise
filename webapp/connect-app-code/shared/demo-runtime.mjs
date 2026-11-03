// Generated code executes only inside QuickJS/WASM, with no host callbacks or module loader.
export const MODULE_IDS = ['display', 'joystick', 'encoder', 'buttons', 'speaker'];
export function validatePackage(app, modules = MODULE_IDS) {
  if (!app || typeof app !== 'object' || Array.isArray(app)) throw Error('Invalid app package.');
  if (
    typeof app.title !== 'string' ||
    !app.title.trim() ||
    app.title.length > 80 ||
    typeof app.description !== 'string' ||
    app.description.length > 400 ||
    typeof app.code !== 'string' ||
    app.code.length < 20 ||
    app.code.length > 40000
  )
    throw Error('Invalid title, description or source size.');
  if (
    !Array.isArray(app.requires) ||
    !app.requires.includes('display') ||
    app.requires.some((m) => !MODULE_IDS.includes(m))
  )
    throw Error('Invalid required components.');
  const missing = app.requires.filter((m) => !modules.includes(m));
  if (missing.length) throw Error(`Attach ${missing.join(', ')} to run this app.`);
  if (
    !app.controls ||
    typeof app.controls !== 'object' ||
    Array.isArray(app.controls) ||
    Object.entries(app.controls).some(
      ([k, v]) => !app.requires.includes(k) || typeof v !== 'string' || v.length > 160,
    )
  )
    throw Error('Invalid control descriptions.');
  return app;
}
const color = (value) => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
const number = (value) =>
  typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= 4096;
export function validateFrame(frame, modules) {
  if (!Array.isArray(frame) || frame.length < 1 || frame.length > 160 || frame[0]?.op !== 'clear')
    throw Error('Each frame must begin with clear and contain 1–160 commands.');
  let tones = 0;
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
});
export function createMachine(QuickJS, app, modules) {
  validatePackage(app, modules);
  const rt = QuickJS.newRuntime();
  rt.setMemoryLimit(16 * 1024 * 1024);
  rt.setMaxStackSize(256 * 1024);
  let deadline = Date.now() + 150;
  rt.setInterruptHandler(() => Date.now() > deadline);
  const vm = rt.newContext();
  let dispatch,
    disposed = false;
  const unwrap = (result) => {
    if (result.error) {
      const message = vm.dump(result.error)?.message || 'Runtime rejected the app';
      result.error.dispose();
      throw Error(String(message).slice(0, 240));
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
export function verifyPackage(QuickJS, app, modules) {
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
        'bounded state, drawing and audio',
      ],
    };
  } finally {
    machine.close();
  }
}
