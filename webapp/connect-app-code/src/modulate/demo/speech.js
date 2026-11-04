// Opt-in spoken replies for the online demo. Meta's open-weight MMS English
// voice (facebook/mms-tts-eng, ONNX port Xenova/mms-tts-eng) runs in the
// visitor's browser via transformers.js + onnxruntime-web (WASM, CPU), as the
// physical device runs the same model on its Pi CPU. Nothing downloads until
// load() is called, which must happen from an explicit user click.

const MODEL_ID = 'Xenova/mms-tts-eng';
const MODEL_REVISION = '3f8955a2adbd6487ce57420620d4916de22b9dac'; // Pinned Hub commit.
const ORT_ROOT = '/ort'; // Self-hosted by scripts/copy-ort-wasm.mjs; never a CDN.
const MAX_CHARS = 300;
const PHRASE_GAP = 0.12; // Seconds between sentences; MMS itself ignores punctuation.
const MESSAGES = {
  unsupported: 'Spoken replies are not supported in this browser.',
  audio: 'Could not start audio in this browser.',
  load: 'Could not load the voice. Check your connection and try again.',
  speak: 'Could not speak that reply.',
};

const ONES = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(' ');
const TENS = 'zero ten twenty thirty forty fifty sixty seventy eighty ninety'.split(' ');
const SCALES = [[1e9, 'billion'], [1e6, 'million'], [1e3, 'thousand'], [100, 'hundred']];

function spokenNumber(n) {
  if (n < 20) return ONES[n];
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? ` ${ONES[n % 10]}` : '');
  const [size, name] = SCALES.find(([scale]) => n >= scale);
  return `${spokenNumber(Math.floor(n / size))} ${name}${n % size ? ` ${spokenNumber(n % size)}` : ''}`;
}

const digits = (value) => [...value].map((digit) => ONES[digit]).join(' ');

// The MMS English vocabulary is letters, space, apostrophe and hyphens, so digits
// and symbols would be dropped. Mirrors normalize() in modulate/mms_worker.py.
function normalize(text) {
  return text.replace(/[\u2018\u2019]/g, "'").replace(/%/g, ' percent').replace(/&/g, ' and ')
    .replace(/(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?/g, (match) => {
      const [whole, fraction] = match.replace(/,/g, '').split('.');
      const words = whole.length > 12 ? digits(whole) : spokenNumber(Number(whole));
      return ` ${words}${fraction ? ` point ${digits(fraction)}` : ''} `;
    });
}

// Normalize, cap at MAX_CHARS on a word boundary, then split into sentences so
// the first can play while the rest is synthesized.
function toPhrases(text) {
  let clean = normalize(String(text ?? '').slice(0, 4 * MAX_CHARS)).replace(/\s+/g, ' ').trim();
  if (clean.length > MAX_CHARS) {
    clean = clean.slice(0, MAX_CHARS);
    const cut = clean.lastIndexOf(' ');
    if (cut > MAX_CHARS / 2) clean = clean.slice(0, cut);
  }
  return (clean.match(/[^.!?;:]+(?:[.!?;:]+|$)/g) ?? []).map((phrase) => phrase.trim()).filter((phrase) => /[a-z]/i.test(phrase));
}

const audioContextClass = () => (typeof window === 'undefined' ? undefined : window.AudioContext || window.webkitAudioContext);

export function isMmsVoiceSupported() {
  return typeof WebAssembly === 'object' && typeof WebAssembly.instantiate === 'function' && typeof audioContextClass() === 'function';
}

export function createMmsVoice({ onStatus } = {}) {
  let state = 'idle';
  let synthesize = null;
  let loading = null;
  let context = null;
  let playback = null; // { sources: Set<AudioBufferSourceNode>, finish() }
  let turn = 0; // Bumped by every stop; stale synthesis results are discarded.

  function emit(next, detail = {}) {
    state = next;
    try { onStatus?.({ state, ...detail }); } catch { /* A UI callback must not break the voice. */ }
  }

  function halt() {
    turn += 1;
    const active = playback;
    playback = null;
    if (!active) return;
    for (const source of active.sources) {
      try { source.onended = null; source.stop(); source.disconnect(); } catch { /* Already stopped. */ }
    }
    active.finish();
  }

  function stop() {
    halt();
    if (state === 'speaking') emit('ready');
  }

  function load() {
    if (synthesize) {
      if (state === 'error') emit('ready');
      return Promise.resolve();
    }
    if (loading) return loading;
    if (!isMmsVoiceSupported()) {
      emit('error', { error: MESSAGES.unsupported });
      return Promise.resolve();
    }
    try {
      // Created synchronously inside the user's click so later replies can play.
      context ??= new (audioContextClass())();
      if (context.state === 'suspended') context.resume().catch(() => {});
    } catch {
      emit('error', { error: MESSAGES.audio });
      return Promise.resolve();
    }
    let reported = 0;
    emit('loading', { progress: 0 });
    loading = (async () => {
      try {
        const { pipeline, env } = await import('@huggingface/transformers');
        env.allowLocalModels = false;
        env.allowRemoteModels = true;
        const { wasm, versions } = env.backends.onnx;
        const base = `${ORT_ROOT}/${versions.web}`;
        wasm.wasmPaths = { mjs: `${base}/ort-wasm-simd-threaded.mjs`, wasm: `${base}/ort-wasm-simd-threaded.wasm` };
        wasm.numThreads = 1;
        // Run inference in onnxruntime's same-origin proxy worker; on the main
        // thread each sentence froze the page for seconds. Downloads stay here.
        wasm.proxy = true;
        synthesize = await pipeline('text-to-speech', MODEL_ID, {
          revision: MODEL_REVISION,
          dtype: 'q8', // onnx/model_quantized.onnx: 38 MB instead of 114 MB.
          device: 'wasm',
          progress_callback: (info) => {
            if (info?.status !== 'progress_total' || !(info.total > 0)) return;
            const progress = Math.min(1, Math.floor((info.loaded / info.total) * 100) / 100);
            if (progress > reported) emit('loading', { progress: (reported = progress) });
          },
        });
        emit('ready');
      } catch {
        emit('error', { error: MESSAGES.load });
      } finally {
        loading = null;
      }
    })();
    return loading;
  }

  async function speak(text) {
    halt();
    const phrases = synthesize ? toPhrases(text) : []; // Silent until load() has finished.
    if (!phrases.length) {
      if (state === 'speaking') emit('ready');
      return;
    }
    const token = turn;
    let finish;
    const ended = new Promise((resolve) => { finish = resolve; });
    const active = { sources: new Set(), finish };
    playback = active;
    emit('speaking');
    try {
      if (context.state !== 'running') context.resume().catch(() => {});
      let startAt = 0;
      let last = null;
      for (const phrase of phrases) {
        // stop() settles `ended`, so a cancelled reply returns without waiting
        // for the in-flight sentence; its late result is discarded.
        const output = await Promise.race([synthesize(phrase), ended]);
        if (token !== turn) return;
        const samples = output?.audio instanceof Float32Array ? output.audio : output?.data;
        if (!samples?.length) continue;
        const buffer = context.createBuffer(1, samples.length, output.sampling_rate);
        buffer.getChannelData(0).set(samples);
        const source = context.createBufferSource();
        source.buffer = buffer;
        source.connect(context.destination);
        startAt = Math.max(startAt, context.currentTime + 0.02);
        source.start(startAt);
        startAt += buffer.duration + PHRASE_GAP;
        active.sources.add(source);
        last = source;
      }
      if (!last) throw new Error('No audio was synthesized');
      last.onended = finish;
      // Fallback for a suspended context that never fires "ended".
      const watchdog = setTimeout(finish, (startAt - context.currentTime + 2) * 1000);
      await ended;
      clearTimeout(watchdog);
      if (token !== turn) return;
      halt();
      emit('ready');
    } catch {
      if (token !== turn) return;
      halt();
      emit('error', { error: MESSAGES.speak });
    }
  }

  return {
    load,
    speak,
    stop,
    get state() { return state; },
  };
}
