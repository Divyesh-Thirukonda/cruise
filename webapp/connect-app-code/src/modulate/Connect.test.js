import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import Connect from './Connect';
import { command, connectApi } from './api';
import { usePathname, useRouter } from 'next/navigation';

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

test('a connected but silent speaker and expiring Mac session are visible before a demo', async () => {
  connectApi.mockImplementation(async action => action === 'session' ? connectedSession : {
    ...initialState,
    device: { ...initialState.device, telemetry: { speaker_volume: { available: true, volume: 0, muted: false } } },
    setup_status: { pairing_expires_at: Date.now()/1000 + 600 },
  });
  render(<Connect />);
  expect(await screen.findByText(/speaker is at 0%/)).toHaveTextContent('Spoken replies will be silent');
  expect(screen.getByText(/Mac access expires/)).toHaveTextContent('confirmation on the device is required');
  expect(command).not.toHaveBeenCalled();
});

test('linked setup shows the pending Mac comparison without a web approval action', async () => {
  usePathname.mockReturnValue('/connect/setup');
  connectApi.mockImplementation(async action => action === 'session' ? connectedSession : {
    ...initialState, paired: false, mac_pairing: { code: '87654321', expires_at: Date.now()/1000 + 120 },
  });
  render(<Connect />);
  expect(await screen.findByLabelText('Mac comparison code')).toHaveTextContent('87654321');
  expect(screen.getByText(/This website cannot approve native access/)).toBeInTheDocument();
  expect(command).not.toHaveBeenCalled();
});

test('unlinked setup never fetches or displays a Mac comparison code', async () => {
  usePathname.mockReturnValue('/connect/setup');
  connectApi.mockResolvedValue({ connected: false, companion: { online: true, platform: 'linux' } });
  render(<Connect />);
  await screen.findByRole('heading', { name: '1. Link this browser.' });
  expect(screen.queryByLabelText('Mac comparison code')).not.toBeInTheDocument();
  expect(connectApi.mock.calls.some(([action]) => action === 'state')).toBe(false);
});

beforeEach(() => {
  jest.clearAllMocks();
  usePathname.mockReturnValue('/connect/studio');
  command.mockResolvedValue({ ok: true });
});

test('first visit only asks for a code and linking preserves access until the next step', async () => {
  usePathname.mockReturnValue('/connect');
  let linked = false;
  connectApi.mockImplementation(async (action, payload) => {
    if (action === 'session' && payload?.code) { linked = true; return connectedSession; }
    return action === 'session' ? linked ? connectedSession : { connected: false } : initialState;
  });
  render(<Connect />);
  await waitFor(() => expect(screen.getByLabelText(/connection code/i)).toBeEnabled());
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/connection code/i), { target: { value: '01234567' } });
  fireEvent.click(screen.getByRole('button', { name: 'Connect to Modulate' }));
  await screen.findByRole('heading', { name: 'Make it yours.' });
  expect(connectApi).toHaveBeenCalledWith('session', { code: '01234567', name: 'Modulate web browser' });
  expect(connectApi.mock.calls.some(([action]) => action === 'permissions')).toBe(false);
  expect(useRouter().push).toHaveBeenCalledWith('/connect/access');
  expect(useRouter().replace).not.toHaveBeenCalledWith('/connect/studio');
  expect(screen.getByRole('switch', { name: 'Allow system controls' })).toHaveAttribute('aria-checked', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Keep current access' }));
  await screen.findByLabelText('What should it become?');
  expect(connectApi.mock.calls.some(([action]) => action === 'permissions')).toBe(false);
});

test('access review saves only changed choices and stays put after a failed save', async () => {
  usePathname.mockReturnValue('/connect/access');
  connectApi.mockImplementation(async action => {
    if (action === 'session') return connectedSession;
    if (action === 'permissions') throw new Error('Save unavailable');
    return initialState;
  });
  render(<Connect />);
  const toggle = await screen.findByRole('switch', { name: 'Allow computer use' });
  fireEvent.click(toggle);
  fireEvent.click(screen.getByRole('button', { name: 'Save & open Studio' }));
  await screen.findByText('Save unavailable');
  expect(connectApi).toHaveBeenCalledWith('permissions', { permissions: { computer: true } });
  expect(screen.getByRole('heading', { name: 'Make it yours.' })).toBeInTheDocument();
  expect(toggle).toHaveAttribute('aria-checked', 'true');
  expect(useRouter().push).not.toHaveBeenCalledWith('/connect/studio');
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
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Modulate workspace' })).getByRole('button', { name: 'Access' }));
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
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Modulate workspace' })).getByRole('button', { name: 'Access' }));
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
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Modulate workspace' })).getByRole('button', { name: 'Access' }));
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
    expect(screen.getByText('Your Modulate connection isn’t reachable yet. Ask your setup agent to finish or reconnect it.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Disconnect browser' })).toBeInTheDocument();
    offline = false;
    await act(async () => { jest.advanceTimersByTime(document.hidden ? 8000 : 1500); });
    expect(within(screen.getByRole('region', { name: 'Device connection' })).getByText('Connected')).toBeInTheDocument();
    expect(screen.queryByText('Your Modulate connection isn’t reachable yet. Ask your setup agent to finish or reconnect it.')).not.toBeInTheDocument();
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
  await screen.findByText('Your Modulate connection isn’t reachable yet. Ask your setup agent to finish or reconnect it.');
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

test('an initial connection failure is visible and links to setup without leaking backend details', async () => {
  usePathname.mockReturnValue('/connect');
  connectApi.mockRejectedValue(Object.assign(new Error('private gateway trace and credential'), { status: 502 }));
  render(<Connect />);
  await screen.findByText('Your Modulate connection isn’t reachable yet. Ask your setup agent to finish or reconnect it.');
  expect(screen.queryByText(/private gateway trace/)).not.toBeInTheDocument();
  expect(screen.queryByText('Browser connected')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Get connection help' }));
  expect(useRouter().push).toHaveBeenCalledWith('/connect/setup');
  expect(screen.getByRole('heading', { name: /Just Modulate and Wi-Fi/ })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Copy Mac setup prompt' })).toBeInTheDocument();
  expect(connectApi.mock.calls.every(([, payload]) => payload === undefined)).toBe(true);
});

test('a recovered initial session check clears the warning without creating a browser session', async () => {
  jest.useFakeTimers();
  usePathname.mockReturnValue('/connect');
  let unavailable = true;
  connectApi.mockImplementation(async () => {
    if (unavailable) throw new Error('Network down');
    return { connected: false };
  });
  try {
    render(<Connect />);
    await screen.findByRole('button', { name: 'Get connection help' });
    unavailable = false;
    await act(async () => { jest.advanceTimersByTime(document.hidden ? 8000 : 1500); });
    expect(screen.queryByRole('button', { name: 'Get connection help' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect to Modulate' })).toBeInTheDocument();
    expect(screen.queryByText('Browser connected')).not.toBeInTheDocument();
    expect(connectApi.mock.calls.every(([, payload]) => payload === undefined)).toBe(true);
  } finally { jest.useRealTimers(); }
});

test('returning to the website retains a valid browser session and opens its workspace', async () => {
  usePathname.mockReturnValue('/connect');
  connectApi.mockImplementation(async action => action === 'session' ? connectedSession : initialState);
  render(<Connect />);
  await screen.findByText('Hey Meta is on');
  expect(useRouter().replace).toHaveBeenCalledWith('/connect/studio');
  expect(screen.queryByRole('button', { name: 'Connect to Modulate' })).not.toBeInTheDocument();
  expect(connectApi.mock.calls.every(([, payload]) => payload === undefined)).toBe(true);
});

test('a failed browser claim stays on the connection form and gives actionable help', async () => {
  usePathname.mockReturnValue('/connect');
  connectApi.mockImplementation(async (action, payload) => {
    if (payload?.code) throw Object.assign(new Error('private upstream traceback'), { status: 503 });
    return { connected: false };
  });
  render(<Connect />);
  await waitFor(() => expect(screen.getByLabelText(/connection code/i)).toBeEnabled());
  fireEvent.change(screen.getByLabelText(/connection code/i), { target: { value: '01234567' } });
  fireEvent.click(screen.getByRole('button', { name: 'Connect to Modulate' }));
  await screen.findByText('Your Modulate connection isn’t reachable yet. Ask your setup agent to finish or reconnect it.');
  expect(screen.getByLabelText(/connection code/i)).toHaveValue('01234567');
  expect(screen.queryByText(/private upstream/)).not.toBeInTheDocument();
  expect(useRouter().push).not.toHaveBeenCalledWith('/connect/access');
});

test('a failed preview retries after reconnecting without a new app revision', async () => {
  let offline = false;
  connectApi.mockImplementation(async action => {
    if (offline) throw new Error('Temporary tunnel outage');
    return action === 'session' ? connectedSession : {
      ...initialState, active: { kind: 'game', revision: 'unchanged-revision', package: { title: 'Same game' } },
    };
  });
  render(<Connect />);
  const label = 'Actual host-rendered preview of the active Modulate program';
  fireEvent.error(await screen.findByAltText(label));
  expect(screen.queryByAltText(label)).not.toBeInTheDocument();
  offline = true;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  await screen.findByText('Your Modulate connection isn’t reachable yet. Ask your setup agent to finish or reconnect it.');
  offline = false;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  expect(await screen.findByAltText(label)).toBeInTheDocument();
  expect(command).not.toHaveBeenCalled();
});


test('detected unknown boards are listed separately from ready runtime controls', async () => {
  usePathname.mockReturnValue('/connect/device');
  connectApi.mockImplementation(async action => action === 'session' ? connectedSession : {
    ...initialState, device: { ...initialState.device, capabilities: {
      controls: ['encoder'], components: [
        { id: 'imu', model: 'LSM6DS3TR-C', addresses: ['0x6a'], ready: true, status: 'ready' },
        { id: 'i2c:0x39', addresses: ['0x39'], ready: false, status: 'needs_identification' },
      ],
    } },
  });
  render(<Connect />);
  const inventory = await screen.findByLabelText('Detected components');
  expect(within(inventory).getByText(/LSM6DS3TR-C/)).toBeInTheDocument();
  expect(within(inventory).getByText('Needs identification')).toBeInTheDocument();
  expect(command).not.toHaveBeenCalled();
});
