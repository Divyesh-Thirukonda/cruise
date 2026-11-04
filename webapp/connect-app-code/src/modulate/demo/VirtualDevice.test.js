import React from 'react';
import { act, render, screen } from '@testing-library/react';
import VirtualDevice from './VirtualDevice';
const app = {
  id: 'a'.repeat(64),
  title: 'Test app',
  description: 'fixture',
  requires: ['display'],
  controls: {},
  code: 'function init(){return 0}function draw(){return []}function update(s){return s}',
};
let workers;
beforeEach(() => {
  workers = [];
  jest.useFakeTimers();
  global.Worker = class {
    constructor() {
      workers.push(this);
    }
    postMessage = jest.fn();
    terminate = jest.fn();
  };
  jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ fillRect: jest.fn() });
});
afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
  delete global.Worker;
});
test('stale acknowledgements cannot activate a candidate', () => {
  const onReady = jest.fn(),
    onReject = jest.fn();
  render(
    <VirtualDevice
      candidate={app}
      modules={['display']}
      busy
      onReady={onReady}
      onReject={onReject}
    />,
  );
  act(() => workers[0].onmessage({ data: { type: 'ready', revision: 'wrong', frame: [] } }));
  expect(onReady).not.toHaveBeenCalled();
  act(() =>
    workers[0].onmessage({
      data: { type: 'ready', revision: app.id, frame: [{ op: 'clear', color: '#000000' }] },
    }),
  );
  expect(onReady).toHaveBeenCalledWith(app);
});
test('timed out staging terminates the candidate and reports failure', () => {
  const onReject = jest.fn();
  render(
    <VirtualDevice
      candidate={app}
      modules={['display']}
      busy
      onReady={jest.fn()}
      onReject={onReject}
    />,
  );
  act(() => jest.advanceTimersByTime(12000));
  expect(onReject).toHaveBeenCalledWith(expect.stringMatching(/acknowledge/));
  expect(workers[0].terminate).toHaveBeenCalled();
});
test('disconnecting a required component stops play and prevents input', () => {
  const props = { app, modules: ['display'], onReady: jest.fn(), onReject: jest.fn() };
  const view = render(<VirtualDevice {...props} />);
  act(() => workers[0].onmessage({ data: { type: 'ready', revision: app.id, frame: [] } }));
  expect(screen.getByRole('button', { name: 'Play app' })).toBeEnabled();
  view.rerender(<VirtualDevice {...props} modules={[]} />);
  expect(screen.getByRole('button', { name: 'Play app' })).toBeDisabled();
});
