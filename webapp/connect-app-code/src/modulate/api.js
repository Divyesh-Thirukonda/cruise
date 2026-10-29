const BASE = '/api/modulate';
let csrfToken = null;

export async function connectApi(action, payload, { signal } = {}) {
  const mutating = payload !== undefined;
  if (mutating && !csrfToken) await connectApi('session');
  const controller = new AbortController();
  const abort = () => controller.abort();
  const timer = setTimeout(abort, 25000);
  signal?.addEventListener('abort', abort, { once: true });
  try {
  const response = await fetch(`${BASE}?action=${encodeURIComponent(action === 'disconnect' ? 'session' : action)}`, {
    method: action === 'disconnect' ? 'DELETE' : mutating ? 'POST' : 'GET',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: !mutating ? {} : { 'Content-Type': 'application/json', 'X-Modulate-CSRF': csrfToken || '' },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    signal: controller.signal,
  });
  let data;
  try { data = await response.json(); } catch (_) {
    throw new Error('The connection service is unavailable. Please try again in a moment.');
  }
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) csrfToken = null;
    const error = new Error(typeof data.error === 'string' ? data.error : data.error?.message || data.message || 'The request could not be completed.');
    error.status = response.status;
    throw error;
  }
  if (data.csrfToken) csrfToken = data.csrfToken;
  return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('The companion did not respond in time. Please try again.');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

export function command(path, payload = {}) {
  return connectApi('command', { path, payload });
}

export function previewUrl(version) {
  return `${BASE}?action=preview&v=${encodeURIComponent(version || 'latest')}`;
}
