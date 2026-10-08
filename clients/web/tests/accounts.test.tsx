import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

vi.mock('../src/utils/navigation', () => ({ goExternal: vi.fn() }));
import { goExternal } from '../src/utils/navigation';

const status = { ...SAMPLE_STATUS, default_user_id: 'owner-user', owner_bound: true };
const setup = () => userEvent.setup();

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(goExternal).mockReset();
  window.history.replaceState(null, '', '/');
});

// There is no Google in the test hub's account service, so these use a fixture: they check what the page sends and shows,
// not Google's behaviour.
function connected() {
  const hub = createFakeHub({ status });
  Object.assign(hub.data.google, {
    configured: true, client_type: 'web', identity: { email: 'me@example.com' },
    scopes: ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/calendar.events.readonly', 'openid'],
    selected_calendars: ['cal1'],
  });
  hub.data.google.capabilities.gmail = { status: 'connected', enabled: true, last_success: '2030-01-01T00:00:00Z' };
  hub.data.google.capabilities.calendar = { status: 'connected', enabled: true, last_success: '2030-01-01T00:00:00Z' };
  return hub;
}

describe('Google accounts', () => {
  it('shows connection state, last check, granted permissions and the signed-in address', async () => {
    connected();
    renderApp('#/settings/accounts');
    expect(await screen.findByText('Signed in as me@example.com')).toBeInTheDocument();
    expect(screen.getAllByText('Ready to read')).toHaveLength(2);
    expect(screen.getByText('Granted permissions: Read Gmail, Read calendar events, Identify your Google account')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Reconnect' })).toHaveLength(2);
  });

  it('needs setup first: Connect is off and the setup section is open', async () => {
    createFakeHub({ status });
    renderApp('#/settings/accounts');
    expect(await screen.findByText('No Google account connected.')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Connect' })[0]).toBeDisabled();
    expect(screen.getByText(/Google sign-in is not ready yet/)).toBeInTheDocument();
    expect(screen.getByText('One-time Google connection setup').closest('details')).toHaveAttribute('open');
  });

  it('saves the connection file (secret sent once, never shown), and refuses a bad file', async () => {
    const hub = createFakeHub({ status });
    const { container } = renderApp('#/settings/accounts');
    const user = setup();
    const input = (await screen.findByLabelText('Google connection file')) as HTMLInputElement;
    await user.upload(input, new File(['not json'], 'x.json', { type: 'application/json' }));
    await user.click(screen.getByRole('button', { name: 'Save connection setup' }));
    expect(await screen.findByText('This is not a Google connection file.')).toBeInTheDocument();
    await user.upload(input, new File([JSON.stringify({ other: {} })], 'y.json', { type: 'application/json' }));
    await user.click(screen.getByRole('button', { name: 'Save connection setup' }));
    expect(await screen.findByText('Choose a Web application or Desktop app connection file downloaded from Google.')).toBeInTheDocument();
    expect(hub.data.googleCalls.some((c) => c.call === 'PUT /configure')).toBe(false);

    const good = JSON.stringify({ installed: { client_id: 'abc.apps.googleusercontent.com', client_secret: 'GOCSPX-topsecret' } });
    await user.upload(input, new File([good], 'z.json', { type: 'application/json' }));
    await user.click(screen.getByRole('button', { name: 'Save connection setup' }));
    expect(await screen.findByText('Setup saved. Select Connect to sign in with Google.')).toBeInTheDocument();
    const sent = hub.data.googleCalls.find((c) => c.call === 'PUT /configure')!.body;
    expect(sent).toMatchObject({ client_id: 'abc.apps.googleusercontent.com', client_secret: 'GOCSPX-topsecret', client_type: 'desktop', disconnect_existing: false });
    expect(document.body.textContent).not.toContain('GOCSPX-topsecret');
    expect(container.innerHTML).not.toContain('GOCSPX-topsecret');
  });

  it('web connect leaves only for accounts.google.com', async () => {
    const hub = connected();
    hub.data.google.capabilities.gmail.enabled = false;
    renderApp('#/settings/accounts');
    const user = setup();
    await user.click((await screen.findAllByRole('button', { name: /Connect|Reconnect/ }))[0]!);
    await waitFor(() => expect(goExternal).toHaveBeenCalledWith('https://accounts.google.com/o/oauth2/auth?x=1'));

    hub.data.authUrl = 'https://evil.example/phish';
    await user.click(screen.getAllByRole('button', { name: /Connect|Reconnect/ })[0]!);
    expect(await screen.findByText('Unexpected sign-in address')).toBeInTheDocument();
    expect(goExternal).toHaveBeenCalledTimes(1);
  });

  it('desktop connect shows a quoted helper command and waits, then finishes when the hub reports it connected', async () => {
    const hub = connected();
    hub.data.google.client_type = 'desktop';
    hub.data.google.capabilities.gmail.enabled = false;
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'Date'], shouldAdvanceTime: true });
    try {
      renderApp('#/settings/accounts');
      const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTimeAsync(ms) });
      await user.click((await screen.findAllByRole('button', { name: 'Connect' }))[0]!);
      const command = await screen.findByText(/python3 google_auth_helper.py/);
      expect(command.textContent).toContain("--client-id 'id'\\''with'\\''quotes'");
      expect(screen.getByText(/Waiting for the helper to finish/)).toBeInTheDocument();
      hub.data.google.capabilities.gmail.enabled = true;
      await act(async () => { await vi.advanceTimersByTimeAsync(3200); });
      expect(await screen.findByText(/Google connected\./)).toBeInTheDocument();
      expect(screen.queryByText(/python3 google_auth_helper.py/)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('completes the sign-in when Google sends the owner back (?google=return), once', async () => {
    const hub = createFakeHub({ status });
    hub.data.google.configured = true;
    window.history.replaceState(null, '', '/?google=return');
    renderApp('#/settings/accounts');
    expect(await screen.findByText('Signed in as me@example.com')).toBeInTheDocument();
    expect(hub.data.googleCalls.filter((c) => c.call === 'POST /complete')).toHaveLength(1);
    expect(window.location.search).toBe('');
  });

  it('tests a connection, and explains a stale one in words', async () => {
    const hub = connected();
    hub.data.google.capabilities.gmail.status = 'stale';
    renderApp('#/settings/accounts');
    const user = setup();
    expect(await screen.findByText(sayStale)).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: 'Test connection' })[0]!);
    expect(await screen.findByText('Connection checked.')).toBeInTheDocument();
    expect(screen.getAllByText('Ready to read')).toHaveLength(2);
  });

  it('disconnects only after confirmation, and says when Google could not revoke', async () => {
    const hub = connected();
    hub.data.revoked = false;
    renderApp('#/settings/accounts');
    const user = setup();
    await user.click((await screen.findAllByRole('button', { name: 'Disconnect' }))[0]!);
    let dialog = within(await screen.findByRole('dialog', { name: 'Disconnect Google?', hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Cancel' }));
    expect(hub.data.googleCalls.some((c) => c.call === 'POST /disconnect')).toBe(false);
    await user.click(screen.getAllByRole('button', { name: 'Disconnect' })[0]!);
    dialog = within(await screen.findByRole('dialog', { name: 'Disconnect Google?', hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Disconnect' }));
    expect(await screen.findByText(/Google could not be reached to revoke access/)).toBeInTheDocument();
    expect(screen.getByText('No Google account connected.')).toBeInTheDocument();
  });

  it('lists calendars with the saved choice, saves a new choice, and previews events and busy times literally', async () => {
    const hub = connected();
    hub.data.events = [{ title: '<b>Standup</b>', all_day: false, start: '2030-01-03T01:00:00Z' }, { title: 'Holiday', all_day: true, start: '2030-01-04T00:00:00Z' }];
    hub.data.busy = [{ start: '2030-01-03T01:00:00Z', end: '2030-01-03T02:00:00Z' }];
    const { container } = renderApp('#/settings/accounts');
    const user = setup();
    expect(await screen.findByRole('checkbox', { name: 'Work (Asia/Singapore)' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Home (UTC)' })).not.toBeChecked();
    await user.click(screen.getByRole('checkbox', { name: 'Home (UTC)' }));
    await user.click(screen.getByRole('button', { name: 'Save calendar choices' }));
    await waitFor(() => expect(hub.data.googleCalls.find((c) => c.call === 'PUT /selection')?.body).toEqual({ calendar_ids: ['cal1', 'cal2'] }));
    expect(await screen.findByText('Calendar choices saved.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Show upcoming events' }));
    expect(await screen.findByText(/<b>Standup<\/b> · /)).toBeInTheDocument();
    expect(screen.getByText(/Holiday · All day · /)).toBeInTheDocument();
    expect(container.querySelector('b')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Show busy times' }));
    expect(await screen.findByText(/^Busy · /)).toBeInTheDocument();
  });

  it('searches mail and opens one message as plain text; empty and failing searches say so', async () => {
    const hub = connected();
    hub.data.mail = [{ id: 'm/1', sender: 'alice@example.com', subject: 'Plans <i>now</i>' }];
    hub.data.mailBodies['m/1'] = { body: 'Hello <script>x</script>\nBye', snippet: 'Hello' };
    const { container } = renderApp('#/settings/accounts');
    const user = setup();
    await user.type(await screen.findByLabelText('Search your mail'), 'plans');
    await user.click(screen.getByRole('button', { name: 'Show messages' }));
    await waitFor(() => expect(hub.calls).toContain('GET /settings/accounts/google/messages?query=plans'));
    await user.click(await screen.findByRole('button', { name: 'alice@example.com: Plans <i>now</i>' }));
    expect(await screen.findByText(/Hello <script>x<\/script>/)).toBeInTheDocument();
    expect(hub.calls).toContain('GET /settings/accounts/google/messages/m%2F1');
    expect(container.querySelector('script, i')).toBeNull();
    hub.data.mail = [];
    await user.click(screen.getByRole('button', { name: 'Show messages' }));
    expect(await screen.findByText('No matching messages.')).toBeInTheDocument();
    hub.respond((c) => c.includes('/messages?'), () => jsonResponse({ detail: 'reconnect_required' }, 502));
    await user.click(screen.getByRole('button', { name: 'Show messages' }));
    expect(await screen.findByText('Google access has expired or was revoked. Select Reconnect.')).toBeInTheDocument();
  });
});

const sayStale = 'The last check is out of date. Select Test connection to check Google access.';

describe('Coding agent credentials', () => {
  it('saves a credential once, shows only its last four, replaces it and removes it after confirmation', async () => {
    const hub = createFakeHub({ status });
    const { container } = renderApp('#/settings/accounts');
    const user = setup();
    const claude = within(await screen.findByRole('region', { name: 'Claude Code' }));
    expect(claude.getByText('No credential configured yet.')).toBeInTheDocument();
    await user.type(claude.getByLabelText('Claude Code credential value'), 'sk-ant-secret-1234');
    await user.click(claude.getByRole('button', { name: 'Save credential' }));
    expect(await screen.findByText('Claude Code credential saved.')).toBeInTheDocument();
    expect(hub.data.saves[0]).toEqual({ call: 'credential claude-code', body: { kind: 'api_key', value: 'sk-ant-secret-1234' } });
    expect(await screen.findByText(/Credential configured \(ending 1234\)/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('sk-ant-secret-1234');
    expect(container.innerHTML).not.toContain('sk-ant-secret-1234');

    const again = within(screen.getByRole('region', { name: 'Claude Code' }));
    expect(again.getByRole('button', { name: 'Replace credential' })).toBeInTheDocument();
    await user.click(again.getByRole('button', { name: 'Remove credential' }));
    let dialog = within(await screen.findByRole('dialog', { name: 'Remove credential?', hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Cancel' }));
    expect(hub.data.credentials).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: 'Remove credential' }));
    dialog = within(await screen.findByRole('dialog', { name: 'Remove credential?', hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(hub.data.credentials).toHaveLength(0));
    expect(await screen.findByText('Claude Code credential removed.')).toBeInTheDocument();
  });

  it('the account-usage credential has a fixed type and no type picker', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/accounts');
    const user = setup();
    const account = within(await screen.findByRole('region', { name: 'Claude account usage' }));
    expect(account.queryByLabelText('Credential type')).not.toBeInTheDocument();
    await user.type(account.getByLabelText('Claude account usage credential value'), '{{"claudeAiOauth":{{}}');
    await user.click(account.getByRole('button', { name: 'Save credential' }));
    await waitFor(() => expect(hub.data.saves[0]!.body.kind).toBe('oauth_token'));
  });
});
void beforeEach;
