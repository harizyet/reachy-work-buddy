import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, hubBase, onUnauthorized, request } from '../src/api/client';
import { json, stubHub } from './helpers';

afterEach(() => vi.unstubAllGlobals());

describe('hubBase', () => {
  it('resolves to the hub root for the direct and the /hub/ proxied mounts', () => {
    expect(hubBase('http://h/web/')).toBe('');
    expect(hubBase('http://h/web/#/login')).toBe('');
    expect(hubBase('http://h/hub/web/')).toBe('/hub');
    expect(hubBase('http://h/hub/web/index.html#/')).toBe('/hub');
  });
});

describe('request', () => {
  it('sends the CSRF header, same-origin credentials and no-store caching', async () => {
    const calls = stubHub({ '/status': () => json({ ok: true }) });
    await request('/status');
    expect(calls[0]?.headers['X-Reachy-CSRF']).toBe('1');
    const init = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls[0]?.[1];
    expect(init?.credentials).toBe('same-origin');
    expect(init?.cache).toBe('no-store');
  });

  it('sends JSON bodies with a content type, and none for GET', async () => {
    const calls = stubHub({ '/x': () => json({}) });
    await request('/x', { method: 'POST', body: { a: 1 } });
    await request('/x');
    expect(calls[0]?.headers['Content-Type']).toBe('application/json');
    expect(calls[0]?.body).toEqual({ a: 1 });
    expect(calls[1]?.headers['Content-Type']).toBeUndefined();
  });

  it('reports the server detail, and a status message for non-JSON gateway failures', async () => {
    stubHub({ '/a': () => json({ detail: 'Nope' }, 422), '/b': () => new Response('<html>bad gateway</html>', { status: 502 }) });
    await expect(request('/a')).rejects.toMatchObject({ message: 'Nope', status: 422 });
    await expect(request('/b')).rejects.toMatchObject({ message: 'Request failed (502)', status: 502 });
    await expect(request('/b')).rejects.toBeInstanceOf(ApiError);
  });

  it('calls the unauthorized handler on 401 unless the caller expects it', async () => {
    stubHub({ '/s': () => json({ detail: 'Login required' }, 401) });
    const handler = vi.fn();
    const off = onUnauthorized(handler);
    await expect(request('/s')).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
    await expect(request('/s', { expectUnauthorized: true })).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
    off();
    await expect(request('/s')).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);
  });
});
