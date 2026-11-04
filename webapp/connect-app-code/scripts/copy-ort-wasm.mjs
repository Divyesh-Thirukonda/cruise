// Self-host the onnxruntime-web WASM runtime used by the browser MMS voice
// (src/modulate/demo/speech.js) so no script or binary loads from a CDN.
// Copies into a versioned folder; transformers.js caches the binary by URL.
import { copyFile, mkdir, readFile, rm, stat } from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
// Prefer the copy nested under transformers.js in case npm could not hoist it.
const candidates = ['node_modules/@huggingface/transformers/node_modules/onnxruntime-web', 'node_modules/onnxruntime-web'];
let source;
for (const candidate of candidates) {
  try { await stat(path.join(root, candidate, 'package.json')); source = path.join(root, candidate); break; } catch {}
}
if (!source) throw new Error('onnxruntime-web is not installed; run npm ci');
const { version } = JSON.parse(await readFile(path.join(source, 'package.json'), 'utf8'));
const target = path.join(root, 'public/ort');
await rm(target, { recursive: true, force: true });
await mkdir(path.join(target, version), { recursive: true });
// The non-JSEP CPU build is all the WASM execution provider needs (14 MB
// instead of the 27 MB WebGPU-capable asyncify build).
for (const name of ['ort-wasm-simd-threaded.mjs', 'ort-wasm-simd-threaded.wasm']) {
  await copyFile(path.join(source, 'dist', name), path.join(target, version, name));
}
