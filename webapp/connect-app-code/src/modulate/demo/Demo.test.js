import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Demo from './Demo';
import { freshWorkspace, STORAGE_KEY } from './model';
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
const response = () => ({
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
              Array.from(JSON.stringify(result) + '\n', (c) => c.charCodeAt(0)),
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
  fireEvent.click(screen.getByRole('button', { name: 'Generate app' }));
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
  expect(screen.getByText(/Attach a display before/)).toBeInTheDocument();
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
