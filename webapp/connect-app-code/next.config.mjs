/** @type {import('next').NextConfig} */
const nextConfig = {
  agentRules: false,
  poweredByHeader: false,
  // The MMS voice (src/modulate/demo/speech.js) imports transformers.js only in
  // the browser; keep it and its native image/ONNX packages out of the server bundle.
  outputFileTracingExcludes: {
    '/demo': ['.next/node_modules/@huggingface/transformers-*', 'node_modules/@huggingface/transformers/**', 'node_modules/onnxruntime-*/**', 'node_modules/sharp/**', 'node_modules/@img/**'],
  },
  async headers() {
    return [{
      source: '/:path*',
      headers: [
        { key: 'Referrer-Policy', value: 'no-referrer' },
        { key: 'X-Content-Type-Options', value: 'nosniff' },
        { key: 'X-Frame-Options', value: 'DENY' },
      ],
    }];
  },
};

export default nextConfig;
