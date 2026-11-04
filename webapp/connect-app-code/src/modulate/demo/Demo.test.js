import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Demo from './Demo';
import { freshWorkspace, STORAGE_KEY } from './model';
const mockVoice = { load: jest.fn(), speak: jest.fn(), stop: jest.fn(), state: 'idle' };
let mockVoiceStatus;
jest.mock('./speech', () => ({
  isMmsVoiceSupported: () => true,
  createMmsVoice: ({ onStatus }) => {
    mockVoiceStatus = onStatus;
    return mockVoice;
  },
}));
let deviceProps;
jest.mock(
  './VirtualDevice',
  () =>
    function Device(props) {
      deviceProps = props;
      return <div>Test virtual device</div>;
    },
);
const app = {
  title: 'Moon painter',
  description: 'Generated test fixture',
  requires: ['display'],
  controls: { display: 'Canvas' },
  code: 'function init(){return 0}function update(s){return s}function draw(){return []}',
};
const result = {
  type: 'result',
  app,
  revision: 'a'.repeat(64),
  checks: { frames: 151 },
  review: 'Approved',
  inference: { model: 'muse-spark-1.3', calls: [], seconds: 1 },
};
const response = (payload = result) => ({
  ok: true,
  body: {
    getReader: () => {
      let done = false;
      return {
        read: async () => {
          if (done) return { done: true };
          done = true;
          return {
            done: false,
            value: new Uint8Array(
              Array.from(JSON.stringify(payload) + '\n', (c) =>
                Math.min(c.charCodeAt(0), 255),
              ),
            ),
          };
        },
      };
    },
  },
});
beforeEach(() => {
  localStorage.clear();
  global.TextDecoder = require('node:util').TextDecoder;
  global.fetch = jest
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ csrf: 'test' }) })
    .mockResolvedValueOnce(response());
});
afterEach(() => {
  delete global.fetch;
});
function submit() {
  fireEvent.change(screen.getByRole('textbox', { name: 'Demo request' }), {
    target: { value: 'Paint the moon with the joystick' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
}
test('a real API result activates only after matching browser verification and persists', async () => {
  render(<Demo />);
  submit();
  await waitFor(() => expect(deviceProps.candidate?.title).toBe('Moon painter'));
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).apps).toHaveLength(0);
  act(() => deviceProps.onReady(deviceProps.candidate));
  expect(screen.getByRole('heading', { name: 'Moon painter' })).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).apps).toHaveLength(1);
  expect(fetch.mock.calls[1][0]).toBe('/api/demo');
  expect(JSON.parse(fetch.mock.calls[1][1].body).prompt).toMatch(/moon/);
});
test('cancel ignores a late successful inference', async () => {
  let resolve;
  fetch
    .mockReset()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ csrf: 'test' }) })
    .mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
  render(<Demo />);
  submit();
  await waitFor(() => expect(resolve).toBeDefined());
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  await act(async () => resolve(response()));
  expect(deviceProps.candidate).toBeNull();
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).apps).toHaveLength(0);
});
test('failed virtual activation keeps the previous library intact', async () => {
  render(<Demo />);
  submit();
  await waitFor(() => expect(deviceProps.candidate).toBeTruthy());
  act(() => deviceProps.onReject('Runtime check failed'));
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).apps).toHaveLength(0);
  expect(screen.getByText(/Runtime check failed/)).toBeInTheDocument();
});
test('no display rejects locally without spending', () => {
  render(<Demo />);
  fireEvent.click(screen.getByRole('button', { name: 'Remove mini display' }));
  submit();
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.getByText(/Attach a display before asking/)).toBeInTheDocument();
});

test('loading and rolling back saved apps verifies locally without inference', () => {
  const first = { ...app, id: 'a'.repeat(64), inference: result.inference };
  const second = { ...app, id: 'b'.repeat(64), title: 'Second app', inference: result.inference };
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ ...freshWorkspace(), apps: [first, second], activeId: first.id }),
  );
  render(<Demo />);
  fireEvent.click(screen.getByRole('button', { name: /App library/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Open app' }));
  expect(deviceProps.candidate.id).toBe(second.id);
  act(() => deviceProps.onReady(deviceProps.candidate));
  fireEvent.click(screen.getByRole('button', { name: 'Restore previous app' }));
  expect(deviceProps.candidate.id).toBe(first.id);
  act(() => deviceProps.onReady(deviceProps.candidate));
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).activeId).toBe(first.id);
  expect(fetch).not.toHaveBeenCalled();
});

const answer = (payload) => {
  fetch
    .mockReset()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ csrf: 'test' }) })
    .mockResolvedValueOnce(response(payload));
};
const meta = { model: 'muse-spark-1.3', calls: [{ role: 'orchestrator', usage: {} }], seconds: 2 };
test('a Muse message can map the knob to the paired computer; turns apply locally', async () => {
  answer({
    type: 'result',
    kind: 'controls',
    app: {
      kind: 'controls',
      title: 'Knob brightness',
      description: 'Mapping',
      requires: ['display', 'computer', 'encoder'],
      controls: { encoder: 'Knob: brightness +2' },
      bindings: [{ control: 'encoder', target: 'computer.brightness', step: 2 }],
    },
    revision: 'd'.repeat(64),
    checks: { passed: true },
    review: 'checked',
    say: 'The knob now controls brightness.',
    inference: meta,
    trace: [{ role: 'orchestrator', title: 'bind', detail: '', status: 'done', at: 1 }],
  });
  render(<Demo />);
  fireEvent.click(screen.getByRole('tab', { name: /Message from Muse/ }));
  submit();
  await waitFor(() => expect(deviceProps.candidate?.kind).toBe('controls'));
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toMatchObject({
    channel: 'muse',
    computer: { brightness: 70, volume: 40 },
  });
  act(() => deviceProps.onReady(deviceProps.candidate));
  act(() => deviceProps.onComputer({ brightness: 72, volume: 40 }));
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).computer.brightness).toBe(72);
  expect(screen.getByText('Orchestrator · bind')).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(2);
});
test('a refusal changes nothing and is shown in the conversation', async () => {
  answer({
    type: 'result',
    kind: 'decline',
    say: 'I can not help clone access badges, but I can build a badge-themed game.',
    inference: meta,
    trace: [],
  });
  render(<Demo />);
  submit();
  await waitFor(() => expect(screen.getAllByText(/clone access badges/).length).toBeGreaterThan(0));
  expect(deviceProps.candidate).toBeNull();
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).apps).toHaveLength(0);
});
test('library results favorite by revision and the device menu follows the starred app', async () => {
  const first = { ...app, id: 'a'.repeat(64), inference: result.inference };
  const second = { ...app, id: 'b'.repeat(64), title: 'Corridor', inference: result.inference };
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ ...freshWorkspace(), apps: [first, second], activeId: second.id }),
  );
  answer({
    type: 'result',
    kind: 'library',
    library: { op: 'favorite', entry: first.id, control: null },
    say: 'Starred.',
    inference: meta,
    trace: [],
  });
  render(<Demo />);
  submit();
  await waitFor(() =>
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).apps[0].favorite).toBe(true),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Library on device' }));
  expect(deviceProps.library.entries[0].id).toBe(first.id);
  act(() => deviceProps.onLibrary({ type: 'move', delta: 1 }));
  expect(deviceProps.library.selected).toBe(1);
});
test('a driver install runs only through the trusted bench and readies the sensor', async () => {
  jest.useFakeTimers();
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ ...freshWorkspace(), hardware: { imuDriver: 'missing', extraButton: null } }),
  );
  answer({
    type: 'result',
    kind: 'debug',
    debug: { op: 'install_driver', driver: 'lsm6ds3trc' },
    say: 'Installing the motion sensor driver.',
    inference: meta,
    trace: [],
  });
  render(<Demo />);
  expect(deviceProps.modules).not.toContain('imu');
  submit();
  await waitFor(() => expect(screen.getByText('Installing a verified driver')).toBeInTheDocument());
  await act(async () => {
    await jest.advanceTimersByTimeAsync(4000);
  });
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).hardware.imuDriver).toBe('ready');
  expect(deviceProps.modules).toContain('imu');
  jest.useRealTimers();
});

test('replies are spoken only after the visitor turns on the in-browser Meta voice', async () => {
  answer({
    type: 'result',
    kind: 'reply',
    say: 'I can build games for the parts you attach.',
    inference: meta,
    trace: [],
  });
  render(<Demo />);
  fireEvent.click(screen.getByRole('button', { name: 'Voice off' }));
  expect(mockVoice.load).toHaveBeenCalledTimes(1);
  act(() => mockVoiceStatus({ state: 'loading', progress: 0.5 }));
  expect(screen.getByRole('button', { name: /Loading Meta voice 50%/ })).toBeInTheDocument();
  act(() => mockVoiceStatus({ state: 'ready' }));
  submit();
  await waitFor(() =>
    expect(mockVoice.speak).toHaveBeenCalledWith('I can build games for the parts you attach.'),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Meta voice on' }));
  expect(mockVoice.stop).toHaveBeenCalled();
});
