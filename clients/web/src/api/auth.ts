import { request } from './client';
import { parseUser } from './types';

export async function fetchMe(signal?: AbortSignal): Promise<{ username: string }> {
  // 401 here means "not signed in", which the caller handles; it is not a session expiry.
  return parseUser(await request('/auth/me', { signal, expectUnauthorized: true }));
}

export async function login(username: string, password: string): Promise<{ username: string }> {
  return parseUser(
    await request('/auth/login', { method: 'POST', body: { username, password }, expectUnauthorized: true }),
  );
}

export async function logout(): Promise<void> {
  await request('/auth/logout', { method: 'POST' });
}
