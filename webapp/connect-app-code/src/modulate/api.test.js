describe('Modulate connection transport', () => {
  beforeEach(() => { jest.resetModules(); global.fetch = jest.fn(); });
  afterEach(() => { delete global.fetch; });

  const response = data => ({ ok: true, status: 200, json: async () => data });

  test('obtains CSRF before pairing, then uses the rotated token for commands', async () => {
    fetch.mockResolvedValueOnce(response({ connected: false, csrfToken: 'before-pair' }))
      .mockResolvedValueOnce(response({ connected: true, csrfToken: 'after-pair' }))
      .mockResolvedValueOnce(response({ ok: true }));
    const { connectApi, command } = require('./api');
    await connectApi('session', { code: '12345678' });
    await command('/api/cancel', {});
    expect(fetch.mock.calls[1][1].headers['X-Modulate-CSRF']).toBe('before-pair');
    expect(fetch.mock.calls[2][1].headers['X-Modulate-CSRF']).toBe('after-pair');
    expect(fetch.mock.calls[2][1].credentials).toBe('same-origin');
  });

  test('disconnect revokes the session with DELETE and CSRF', async () => {
    fetch.mockResolvedValueOnce(response({ csrfToken: 'csrf-value' })).mockResolvedValueOnce(response({ connected: false }));
    const { connectApi } = require('./api');
    await connectApi('disconnect', {});
    expect(fetch).toHaveBeenLastCalledWith('/api/modulate?action=session', expect.objectContaining({
      method: 'DELETE', headers: expect.objectContaining({ 'X-Modulate-CSRF': 'csrf-value' }),
    }));
  });
});

describe('uncertain command outcomes', () => {
  beforeEach(() => { jest.resetModules(); global.fetch = jest.fn(); });
  afterEach(() => { delete global.fetch; jest.useRealTimers(); });
  const session = { ok: true, status: 200, json: async () => ({ csrfToken: 'test-csrf' }) };

  test.each(['network', 'gateway'])('%s failure warns that the command may have run and never replays it', async failure => {
    fetch.mockResolvedValueOnce(session);
    if (failure === 'network') fetch.mockRejectedValueOnce(new TypeError('fetch failed'));
    else fetch.mockResolvedValueOnce({ ok: false, status: 502, json: async () => ({ error: 'Try again' }) });
    const { command } = require('./api');
    await expect(command('/api/request', { text: 'make a game' })).rejects.toThrow('may already have run');
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  test('an already cancelled request never fetches or submits a command', async () => {
    const controller = new AbortController(); controller.abort();
    const { connectApi } = require('./api');
    await expect(connectApi('command', {}, { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetch).not.toHaveBeenCalled();
  });

  test('a timed out command warns about its uncertain outcome without retrying', async () => {
    jest.useFakeTimers();
    fetch.mockResolvedValueOnce(session).mockImplementationOnce((url, options) => new Promise((_, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('timeout', 'AbortError')));
    }));
    const { command } = require('./api');
    const pending = expect(command('/api/request', { text: 'make a game' })).rejects.toThrow('may already have run');
    await jest.advanceTimersByTimeAsync(25000);
    await pending;
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});

  test('cancellation while session credentials load prevents the command from dispatching', async () => {
    jest.resetModules();
    let resolve;
    global.fetch = jest.fn(() => new Promise(yes => { resolve = yes; }));
    const { connectApi } = require('./api');
    const controller = new AbortController();
    const result = expect(connectApi('command', {}, { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
    controller.abort();
    resolve({ ok: true, json: async () => ({ csrfToken: 'test' }) });
    await result;
    expect(fetch).toHaveBeenCalledTimes(1);
    delete global.fetch;
  });
