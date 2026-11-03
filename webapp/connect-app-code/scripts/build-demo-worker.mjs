import { build } from 'esbuild';
await build({
  entryPoints: ['src/modulate/demo/runtime-worker.js'],
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: ['es2022'],
  outfile: 'public/demo-runtime.js',
  minify: true,
  legalComments: 'eof',
});
