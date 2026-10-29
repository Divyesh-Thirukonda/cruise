import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import Connect from './Connect';
import { command, connectApi } from './api';

jest.mock('./api', () => ({
  connectApi: jest.fn(), command: jest.fn(), previewUrl: () => '/test-preview.png',
}));

const initialState = {
  device: { connected: true, capabilities: { controls: ['encoder'] }, telemetry: {} },
  agent: { running: false }, events: [], paired: true, wake: true,
};
const connectedSession = { connected: true, companion: { online: true }, permissions: { system: true } };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

beforeEach(() => {
  jest.clearAllMocks();
  command.mockResolvedValue({ ok: true });
});

test('pairing submits the user’s access choices and camera sharing starts off', async () => {
  connectApi.mockResolvedValue({ connected: false });
  render(<Connect />);
  const computerChoice = await screen.findByRole('checkbox', { name: 'Computer use' });
  expect(screen.getByRole('checkbox', { name: 'Camera preview in browsers' })).not.toBeChecked();
  fireEvent.click(computerChoice);
  fireEvent.change(screen.getByLabelText('CONNECTION CODE'), { target: { value: '12345678' } });
  fireEvent.click(screen.getByRole('button', { name: 'Connect to Modulate' }));
  await waitFor(() => expect(connectApi).toHaveBeenCalledWith('session', expect.objectContaining({
    code: '12345678', permissions: expect.objectContaining({ computer: false, camera: true, remote_preview: false }),
  })));
});

test('follow-up answers retain the exact question id', async () => {
  connectApi.mockImplementation(async action => action === 'session'
    ? { connected: true, companion: { online: true }, permissions: {} }
    : { ...initialState, clarification: { id: 'question-42', question: 'Which window?' } });
  render(<Connect />);
  const answer = await screen.findByLabelText('Your answer');
  fireEvent.change(answer, { target: { value: 'The frontmost one' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send request' }));
  await waitFor(() => expect(command).toHaveBeenCalledWith('/api/request', {
    text: 'The frontmost one', followup_id: 'question-42',
  }));
});

test('a failed permissions update does not display a grant as successful', async () => {
  connectApi.mockImplementation(async action => {
    if (action === 'session') return { connected: true, companion: { online: true }, permissions: { computer: false, camera: true, system: true } };
    if (action === 'permissions') throw new Error('Companion unavailable');
    return initialState;
  });
  render(<Connect />);
  await screen.findByText('Hey Meta is on');
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Modulate workspace' })).getByRole('button', { name: 'Permissions' }));
  const toggle = screen.getByRole('switch', { name: 'Allow computer use' });
  expect(toggle).toHaveAttribute('aria-checked', 'false');
  fireEvent.click(toggle);
  await screen.findByText('Companion unavailable');
  expect(connectApi).toHaveBeenCalledWith('permissions', { permissions: { computer: true } });
  expect(toggle).toHaveAttribute('aria-checked', 'false');
});

test('private camera mode does not request a cloud preview frame', async () => {
  connectApi.mockImplementation(async action => action === 'session'
    ? { connected: true, companion: { online: true }, permissions: { camera: true, remote_preview: false } }
    : { ...initialState, active: { revision: 'camera-rev', title: 'Mirror', package: { kind: 'game', camera: true } } });
  render(<Connect />);
  await screen.findByText('Camera preview is private');
  expect(screen.queryByAltText('Actual host-rendered preview of the active Modulate program')).not.toBeInTheDocument();
});

test('opening a paused speech draft restores its transcript without resending it', async () => {
  connectApi.mockImplementation(async action => action === 'session'
    ? { connected: true, companion: { online: true }, permissions: {} }
    : { ...initialState, voice_draft: { job_id: 'paused-draft', text: 'Make the kart purple', editing: true } });
  render(<Connect />);
  const editor = await screen.findByLabelText('Spoken request');
  await waitFor(() => expect(editor).toHaveValue('Make the kart purple'));
  expect(command).not.toHaveBeenCalled();
});

test('disconnect clears private state without waiting for an older poll and ignores its late result', async () => {
  const oldState = deferred();
  const afterDisconnect = deferred();
  let disconnected = false;
  let stateReads = 0;
  const privateState = { ...initialState, active: { revision: 'private-rev', package: { title: 'Private camera app', camera: true } } };
  connectApi.mockImplementation(action => {
    if (action === 'disconnect') { disconnected = true; return Promise.resolve({ ok: true }); }
    if (action === 'session') return disconnected ? afterDisconnect.promise : Promise.resolve(connectedSession);
    stateReads += 1;
    return stateReads === 2 ? oldState.promise : Promise.resolve(privateState);
  });
  render(<Connect />);
  await screen.findByRole('heading', { name: 'Private camera app' });
  fireEvent.click(screen.getByRole('button', { name: 'Refresh', exact: true }));
  await waitFor(() => expect(stateReads).toBe(2));
  fireEvent.click(screen.getByRole('button', { name: 'Disconnect browser' }));
  await screen.findByRole('button', { name: 'Connect to Modulate' });
  expect(screen.queryByRole('heading', { name: 'Private camera app' })).not.toBeInTheDocument();
  await act(async () => { oldState.resolve(privateState); });
  expect(screen.queryByRole('heading', { name: 'Private camera app' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Disconnect browser' })).not.toBeInTheDocument();
  await act(async () => { afterDisconnect.resolve({ connected: false }); });
});

test('a permission update refreshes immediately and an older session cannot restore the old grant', async () => {
  const oldSession = deferred();
  let sessionReads = 0;
  let allowed = true;
  connectApi.mockImplementation(action => {
    if (action === 'permissions') { allowed = false; return Promise.resolve({ ok: true }); }
    if (action === 'session') {
      sessionReads += 1;
      if (sessionReads === 2) return oldSession.promise;
      return Promise.resolve({ ...connectedSession, permissions: { system: allowed } });
    }
    return Promise.resolve(initialState);
  });
  render(<Connect />);
  await screen.findByText('Hey Meta is on');
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Modulate workspace' })).getByRole('button', { name: 'Permissions' }));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh', exact: true }));
  await waitFor(() => expect(sessionReads).toBe(2));
  const toggle = screen.getByRole('switch', { name: 'Allow system controls' });
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'false'));
  expect(toggle).toBeEnabled();
  expect(sessionReads).toBe(3);
  await act(async () => { oldSession.resolve(connectedSession); });
  expect(toggle).toHaveAttribute('aria-checked', 'false');
  expect(connectApi.mock.calls.filter(([action]) => action === 'state')).toHaveLength(2);
});

test('an old authentication error cannot clear a successfully refreshed connection', async () => {
  const oldState = deferred();
  let stateReads = 0;
  connectApi.mockImplementation(action => {
    if (action === 'session') return Promise.resolve(connectedSession);
    if (action === 'permissions') return Promise.resolve({ ok: true });
    stateReads += 1;
    return stateReads === 2 ? oldState.promise : Promise.resolve(initialState);
  });
  render(<Connect />);
  await screen.findByText('Hey Meta is on');
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Modulate workspace' })).getByRole('button', { name: 'Permissions' }));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh', exact: true }));
  await waitFor(() => expect(stateReads).toBe(2));
  fireEvent.click(screen.getByRole('switch', { name: 'Allow system controls' }));
  await waitFor(() => expect(stateReads).toBe(3));
  await act(async () => { oldState.reject(Object.assign(new Error('Expired old request'), { status: 401 })); });
  expect(screen.getByRole('button', { name: 'Disconnect browser' })).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Device connection' })).getByText('Connected')).toBeInTheDocument();
});

test('the connected dashboard waits for device state and simultaneous refreshes share one read', async () => {
  const firstState = deferred();
  const nextState = deferred();
  let stateReads = 0;
  connectApi.mockImplementation(action => {
    if (action === 'session') return Promise.resolve(connectedSession);
    stateReads += 1;
    return stateReads === 1 ? firstState.promise : nextState.promise;
  });
  render(<Connect />);
  await waitFor(() => expect(stateReads).toBe(1));
  expect(screen.getByText('Connecting')).toBeInTheDocument();
  expect(screen.queryByText('Push to talk')).not.toBeInTheDocument();
  expect(screen.queryByText('Not paired')).not.toBeInTheDocument();
  await act(async () => { firstState.resolve(initialState); });
  fireEvent.click(screen.getByRole('button', { name: 'Refresh', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh', exact: true }));
  await waitFor(() => expect(stateReads).toBe(2));
  expect(connectApi.mock.calls.filter(([action]) => action === 'session')).toHaveLength(2);
  await act(async () => { nextState.resolve(initialState); });
  expect(within(screen.getByRole('region', { name: 'Device connection' })).getByText('Connected')).toBeInTheDocument();
});

test('a temporary outage keeps the connection and recovers automatically', async () => {
  jest.useFakeTimers();
  let offline = false;
  connectApi.mockImplementation(async action => {
    if (offline) throw new Error('Companion unavailable');
    return action === 'session' ? connectedSession : initialState;
  });
  try {
    render(<Connect />);
    await screen.findByText('Hey Meta is on');
    offline = true;
    await act(async () => { jest.advanceTimersByTime(document.hidden ? 8000 : 1500); });
    expect(screen.getByText('Your companion is offline. Keep Modulate Studio running on the paired Mac. Retrying automatically.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Disconnect browser' })).toBeInTheDocument();
    offline = false;
    await act(async () => { jest.advanceTimersByTime(document.hidden ? 8000 : 1500); });
    expect(within(screen.getByRole('region', { name: 'Device connection' })).getByText('Connected')).toBeInTheDocument();
    expect(screen.queryByText('Your companion is offline. Keep Modulate Studio running on the paired Mac. Retrying automatically.')).not.toBeInTheDocument();
  } finally { jest.useRealTimers(); }
});

test('an initial state failure retains the authenticated session as offline and can recover', async () => {
  let stateUnavailable = true;
  connectApi.mockImplementation(async action => {
    if (action === 'session') return connectedSession;
    if (stateUnavailable) throw Object.assign(new Error('Companion unavailable'), { status: 502 });
    return initialState;
  });
  render(<Connect />);
  await screen.findByText('Your companion is offline. Keep Modulate Studio running on the paired Mac. Retrying automatically.');
  expect(screen.getByRole('button', { name: 'Disconnect browser' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Connect to Modulate' })).not.toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Device connection' })).queryByText('Connected')).not.toBeInTheDocument();
  expect(screen.queryByAltText('Actual host-rendered preview of the active Modulate program')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Send request' })).toBeDisabled();
  stateUnavailable = false;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh', exact: true }));
  await within(screen.getByRole('region', { name: 'Device connection' })).findByText('Connected');
  expect(screen.getByText('Hey Meta is on')).toBeInTheDocument();
});
