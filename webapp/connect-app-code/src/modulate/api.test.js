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
