import variant from '@jitl/quickjs-singlefile-browser-release-sync';
import { newQuickJSWASMModuleFromVariant } from 'quickjs-emscripten';
import { createMachine, verifyPackage } from '../../../shared/demo-runtime.mjs';
const engine = newQuickJSWASMModuleFromVariant(variant);
let machine = null,
  revision = null;
self.onmessage = async ({ data }) => {
  try {
    if (data.type === 'stage') {
      const QuickJS = await engine;
      const checks = verifyPackage(QuickJS, data.app, data.modules);
      const next = createMachine(QuickJS, data.app, data.modules);
      const frame = next.frame();
      machine?.close();
      machine = next;
      revision = data.revision;
      self.postMessage({ type: 'ready', revision, frame, checks });
    } else if (data.type === 'frame' && machine && data.revision === revision) {
      self.postMessage({ type: 'frame', revision, frame: machine.frame(data.input, data.dt) });
    }
  } catch (error) {
    self.postMessage({
      type: 'error',
      revision: data.revision,
      error: String(error.message).slice(0, 240),
    });
  }
};
