import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { json, renderApp, SAMPLE_STATUS, stubHub } from './helpers';

afterEach(() => vi.unstubAllGlobals());

const signedIn = {
  '/auth/me': () => json({ username: 'owner' }),
  '/status': () => json(SAMPLE_STATUS),
};

describe('protected routing', () => {
  it('shows nothing private and goes to sign-in when the hub says 401', async () => {
    stubHub({ '/auth/me': () => json({ detail: 'Login required' }, 401) });
    renderApp('#/');
    expect(await screen.findByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();
    expect(screen.queryByText('System status')).not.toBeInTheDocument();
    expect(window.location.hash).toBe('#/login');
  });

  it('renders no protected content while the session check is pending', () => {
    stubHub({ '/auth/me': () => new Promise<Response>(() => {}) });
    renderApp('#/');
    expect(screen.getByRole('status')).toHaveTextContent('Checking your session');
    expect(screen.queryByText('System status')).not.toBeInTheDocument();
  });

  it('sends a signed-in owner away from the login page', async () => {
    stubHub(signedIn);
    renderApp('#/login');
    expect(await screen.findByRole('heading', { name: 'System status' })).toBeInTheDocument();
  });

  it('shows a not-found page inside the guard for unknown routes', async () => {
    stubHub(signedIn);
    renderApp('#/nope');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});

describe('sign-in', () => {
  it('posts credentials with the CSRF header, clears the password and reaches Overview', async () => {
    const calls = stubHub({
      '/auth/me': () => json({ detail: 'Login required' }, 401),
      '/auth/login': () => json({ username: 'owner' }),
      '/status': () => json(SAMPLE_STATUS),
    });
    renderApp('#/login');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Username'), 'owner');
    await user.type(screen.getByLabelText('Password'), 'correct-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'System status' })).toBeInTheDocument();
    const login = calls.find((c) => c.path === '/auth/login');
    expect(login?.body).toEqual({ username: 'owner', password: 'correct-password' });
    expect(login?.headers['X-Reachy-CSRF']).toBe('1');
  });

  it('shows the server message for a wrong password and stays on the form', async () => {
    stubHub({
      '/auth/me': () => json({ detail: 'Login required' }, 401),
      '/auth/login': () => json({ detail: 'Invalid username or password' }, 401),
    });
    renderApp('#/login');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Username'), 'owner');
    await user.type(screen.getByLabelText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password');
    expect(screen.getByLabelText('Password')).toHaveValue('');
  });
});

describe('logout and session expiry clear private data', () => {
  it('drops the query cache and the page on logout, even if the request fails', async () => {
    const calls = stubHub({ ...signedIn, '/auth/logout': () => json({ detail: 'boom' }, 500) });
    const { client } = renderApp('#/');
    await screen.findByRole('heading', { name: 'System status' });
    expect(client.getQueryData(['status'])).toBeDefined();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Log out' }));
    expect(await screen.findByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();
    expect(client.getQueryCache().getAll()).toHaveLength(0);
    expect(screen.queryByText('Reachy hub')).not.toBeInTheDocument();
    expect(calls.some((c) => c.path === '/auth/logout' && c.method === 'POST')).toBe(true);
  });

  it('treats a 401 on a data request as an expired session', async () => {
    let expired = false;
    stubHub({
      '/auth/me': () => json({ username: 'owner' }),
      '/status': () => (expired ? json({ detail: 'Login required' }, 401) : json(SAMPLE_STATUS)),
    });
    const { client } = renderApp('#/');
    await screen.findByText('Reachy hub');
    expired = true;
    await client.refetchQueries({ queryKey: ['status'] }).catch(() => undefined);
    expect(await screen.findByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Your session has ended');
    expect(client.getQueryCache().getAll().filter((q) => q.state.data !== undefined)).toHaveLength(0);
  });
});

describe('Overview', () => {
  it('lists components, a registered robot and usage from the hub status', async () => {
    stubHub(signedIn);
    renderApp('#/');
    const card = await screen.findByRole('region', { name: 'Components' });
    for (const name of ['Reachy hub', 'Companion core', 'Language model', 'Telegram', 'desk']) {
      expect(within(card).getByText(name)).toBeInTheDocument();
    }
    expect(within(card).getByText('Not configured')).toBeInTheDocument(); // Telegram
    expect(within(card).getByText('idle')).toBeInTheDocument();
    expect(screen.getByText(/No model calls yet/)).toBeInTheDocument();
  });

  it('shows an error with retry when the status cannot be read', async () => {
    let fail = true;
    stubHub({
      '/auth/me': () => json({ username: 'owner' }),
      '/status': () => (fail ? json({ detail: 'Companion core unavailable' }, 502) : json(SAMPLE_STATUS)),
    });
    renderApp('#/');
    expect(await screen.findByRole('alert')).toHaveTextContent('Companion core unavailable');
    fail = false;
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(screen.getByText('Reachy hub')).toBeInTheDocument());
  });

  it('marks degraded components and never interprets server text as HTML', async () => {
    const hostile = { ...SAMPLE_STATUS, telegram: { ...SAMPLE_STATUS.telegram, configured: true, healthy: false, last_poll_error: '<img src=x onerror=alert(1)>' }, companion_core: { status: 'unavailable' } };
    stubHub({ ...signedIn, '/status': () => json(hostile) });
    const { container } = renderApp('#/');
    await screen.findByText('Reachy hub');
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0);
  });

  it('keeps showing the last status when a refresh fails', async () => {
    let fail = false;
    stubHub({
      '/auth/me': () => json({ username: 'owner' }),
      '/status': () => (fail ? json({ detail: 'down' }, 502) : json(SAMPLE_STATUS)),
    });
    const { client } = renderApp('#/');
    await screen.findByText('Reachy hub');
    fail = true;
    await client.refetchQueries({ queryKey: ['status'] }).catch(() => undefined);
    expect(await screen.findByText(/status may be stale/)).toBeInTheDocument();
    expect(screen.getByText('Reachy hub')).toBeInTheDocument();
  });
});
