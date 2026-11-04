import { waitFor } from '@testing-library/react';
import { pipeline, env } from '@huggingface/transformers';
import { createMmsVoice, isMmsVoiceSupported } from './speech';

jest.mock('@huggingface/transformers', () => ({
  pipeline: jest.fn(),
  env: { backends: { onnx: { wasm: {}, versions: { web: '9.9.9-test' } } } },
}));

class FakeSource {
  constructor(context) { this.context = context; this.onended = null; this.stopped = false; }
  connect() {}
  disconnect() {}
  start(when) { this.when = when; this.context.sources.push(this); }
  stop() { this.stopped = true; }
}

class FakeAudioContext {
  constructor() { this.state = 'running'; this.currentTime = 0; this.destination = {}; this.sources = []; FakeAudioContext.last = this; }
  resume() { this.state = 'running'; return Promise.resolve(); }
  createBuffer(channels, length, sampleRate) {
    const data = new Float32Array(length);
    return { numberOfChannels: channels, length, sampleRate, duration: length / sampleRate, getChannelData: () => data };
  }
  createBufferSource() { return new FakeSource(this); }
}

const audio = () => ({ audio: new Float32Array(8000).fill(0.25), sampling_rate: 16000 });

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

async function readyVoice(synth = jest.fn(async () => audio())) {
  pipeline.mockResolvedValue(synth);
  const statuses = [];
  const voice = createMmsVoice({ onStatus: (status) => statuses.push(status) });
  await voice.load();
  return { voice, statuses, synth, context: FakeAudioContext.last };
}

beforeEach(() => {
  pipeline.mockReset();
  window.AudioContext = FakeAudioContext;
});

afterEach(() => { delete window.AudioContext; });

test('downloads nothing until load(), then reports progress and becomes ready with the self-hosted quantized model', async () => {
  const synth = jest.fn();
  pipeline.mockImplementation(async (task, model, options) => {
    options.progress_callback({ status: 'progress_total', loaded: 19, total: 38 });
    options.progress_callback({ status: 'progress', file: 'onnx/model_quantized.onnx', loaded: 19, total: 38 });
    return synth;
  });
  const statuses = [];
  const voice = createMmsVoice({ onStatus: (status) => statuses.push(status) });
  expect(voice.state).toBe('idle');
  expect(pipeline).not.toHaveBeenCalled();

  await Promise.all([voice.load(), voice.load()]);
  expect(voice.state).toBe('ready');
  expect(statuses).toEqual([{ state: 'loading', progress: 0 }, { state: 'loading', progress: 0.5 }, { state: 'ready' }]);
  expect(pipeline).toHaveBeenCalledTimes(1);
  expect(pipeline).toHaveBeenCalledWith('text-to-speech', 'Xenova/mms-tts-eng', expect.objectContaining({ dtype: 'q8', device: 'wasm', revision: expect.stringMatching(/^[0-9a-f]{40}$/) }));
  expect(env.backends.onnx.wasm).toMatchObject({
    wasmPaths: { mjs: '/ort/9.9.9-test/ort-wasm-simd-threaded.mjs', wasm: '/ort/9.9.9-test/ort-wasm-simd-threaded.wasm' },
    proxy: true,
  });
  expect(env.allowLocalModels).toBe(false);

  await voice.load();
  expect(pipeline).toHaveBeenCalledTimes(1);
});

test('speak() goes speaking → ready, playing each sentence at the model sampling rate and resolving when playback ends', async () => {
  const { voice, statuses, synth, context } = await readyVoice();
  let resolved = false;
  const done = voice.speak('Your game is ready. Tilt to aim, press A to fire.').then(() => { resolved = true; });
  expect(voice.state).toBe('speaking');

  await waitFor(() => expect(context.sources.at(-1)?.onended).toEqual(expect.any(Function)));
  expect(synth.mock.calls.map(([text]) => text)).toEqual(['Your game is ready.', 'Tilt to aim, press A to fire.']);
  expect(context.sources).toHaveLength(2);
  expect(context.sources[0].buffer).toMatchObject({ sampleRate: 16000, length: 8000 });
  expect(context.sources[1].when).toBeGreaterThan(context.sources[0].when + 0.5);
  expect(resolved).toBe(false);

  context.sources[1].onended();
  await done;
  expect(voice.state).toBe('ready');
  expect(statuses.slice(-2).map(({ state }) => state)).toEqual(['speaking', 'ready']);
});

test('speak() caps text at 300 characters and spells out numbers the MMS vocabulary lacks', async () => {
  const { voice, synth, context } = await readyVoice();
  const done = voice.speak(`You scored 1,250 points & 75% accuracy. ${'go '.repeat(200)}`);
  await waitFor(() => expect(context.sources.at(-1)?.onended).toEqual(expect.any(Function)));
  const spoken = synth.mock.calls.map(([text]) => text);
  expect(spoken[0]).toBe('You scored one thousand two hundred fifty points and seventy five percent accuracy.');
  expect(spoken.join(' ').length).toBeLessThanOrEqual(300);
  context.sources.at(-1).onended();
  await done;
});

test('stop() cancels playback and pending synthesis, resolving speak() promptly', async () => {
  const pending = deferred();
  const synth = jest.fn().mockResolvedValueOnce(audio()).mockReturnValueOnce(pending.promise);
  const { voice, context } = await readyVoice(synth);
  const done = voice.speak('First sentence. Second sentence.');
  await waitFor(() => expect(synth).toHaveBeenCalledTimes(2));
  const playing = context.sources[0];

  voice.stop();
  await done;
  expect(playing.stopped).toBe(true);
  expect(voice.state).toBe('ready');

  pending.resolve(audio()); // A late result must not start playback.
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(context.sources).toHaveLength(1);
  expect(voice.state).toBe('ready');
});

test('a new speak() replaces the current reply', async () => {
  const pending = deferred();
  const synth = jest.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(audio());
  const { voice, context } = await readyVoice(synth);
  const first = voice.speak('Old reply.');
  const second = voice.speak('New reply.');
  await first;
  await waitFor(() => expect(context.sources.at(-1)?.onended).toEqual(expect.any(Function)));
  pending.resolve(audio());
  context.sources.at(-1).onended();
  await second;
  expect(context.sources).toHaveLength(1);
  expect(synth.mock.calls.map(([text]) => text)).toEqual(['Old reply.', 'New reply.']);
});

test('load failure surfaces a short error without throwing, keeps replies silent, and can be retried', async () => {
  pipeline.mockRejectedValueOnce(new TypeError('Failed to fetch'));
  const statuses = [];
  const voice = createMmsVoice({ onStatus: (status) => statuses.push(status) });
  await expect(voice.load()).resolves.toBeUndefined();
  expect(voice.state).toBe('error');
  expect(statuses.at(-1)).toEqual({ state: 'error', error: 'Could not load the voice. Check your connection and try again.' });

  await expect(voice.speak('Hello.')).resolves.toBeUndefined();
  expect(voice.state).toBe('error');

  const synth = jest.fn(async () => audio());
  pipeline.mockResolvedValueOnce(synth);
  await voice.load();
  expect(voice.state).toBe('ready');
});

test('synthesis failure surfaces an error and the next reply still plays', async () => {
  const synth = jest.fn().mockRejectedValueOnce(new Error('wasm trap')).mockResolvedValue(audio());
  const { voice, statuses, context } = await readyVoice(synth);
  await expect(voice.speak('Broken.')).resolves.toBeUndefined();
  expect(statuses.at(-1)).toEqual({ state: 'error', error: 'Could not speak that reply.' });

  const done = voice.speak('Working.');
  await waitFor(() => expect(context.sources.at(-1)?.onended).toEqual(expect.any(Function)));
  context.sources.at(-1).onended();
  await done;
  expect(voice.state).toBe('ready');
});

test('reports unsupported browsers instead of loading', async () => {
  delete window.AudioContext;
  expect(isMmsVoiceSupported()).toBe(false);
  const voice = createMmsVoice();
  await voice.load();
  expect(voice.state).toBe('error');
  expect(pipeline).not.toHaveBeenCalled();
});
