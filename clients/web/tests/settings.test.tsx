import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

afterEach(() => vi.unstubAllGlobals());

const status = { ...SAMPLE_STATUS, default_user_id: 'owner-user', owner_bound: true };
const setup = () => userEvent.setup();

describe('Settings navigation', () => {
  it('opens on Assistant; arrow keys, Home and End move between tabs', async () => {
    createFakeHub({ status });
    renderApp('#/settings');
    const user = setup();
    const tabs = await screen.findAllByRole('tab');
    expect(tabs.map((t) => t.textContent)).toEqual(['Assistant', 'Models', 'Web search', 'Voice & motion', 'Display', 'Accounts', 'Owner recognition']);
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
    expect(tabs[1]).toHaveAttribute('tabindex', '-1');
    tabs[0]!.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Models' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Models' })).toHaveFocus();
    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: 'Owner recognition' })).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Assistant' })).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('tab', { name: 'Owner recognition' })).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{Home}');
    expect(screen.getByRole('tab', { name: 'Assistant' })).toHaveFocus();
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', 'settings-assistant-tab');
  });
});

describe('Assistant tab', () => {
  it('saves the session mode and do-not-disturb for the owner', async () => {
    const hub = createFakeHub({ status });
    hub.data.sessions.set('owner-user', { interaction_mode: 'desk', dnd: false, active_channel: 'web' });
    renderApp('#/settings/assistant');
    const user = setup();
    expect(await screen.findByText('Active channel: web')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Mode'), 'silent');
    await user.click(screen.getByRole('checkbox', { name: 'Do not disturb' }));
    await user.click(screen.getByRole('button', { name: 'Save session' }));
    await waitFor(() => expect(hub.calls).toContain('PATCH /sessions/owner-user/dnd'));
    expect(hub.bodies.find((b) => b.call === 'PATCH /sessions/owner-user/mode')?.body).toEqual({ interaction_mode: 'silent' });
    expect(hub.bodies.find((b) => b.call === 'PATCH /sessions/owner-user/dnd')?.body).toEqual({ dnd: true });
    expect(await screen.findByText('Session settings saved.')).toBeInTheDocument();
  });

  it('explains when there is no session yet', async () => {
    createFakeHub({ status });
    renderApp('#/settings/assistant');
    expect(await screen.findByText('No session yet. Your first message will start one.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save session' })).not.toBeInTheDocument();
  });

  it('shows the user field only when the hub is not owner-bound', async () => {
    createFakeHub({ status: { ...status, owner_bound: false } });
    renderApp('#/settings/assistant');
    await waitFor(() => expect(screen.getByLabelText('User ID')).toHaveValue('owner-user'));
  });

  it('saves the persona, loads defaults without saving, and takes the browser time zone', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/assistant');
    const user = setup();
    const name = await screen.findByLabelText('Name');
    expect(name).toHaveValue('Reachy');
    await user.clear(name);
    await user.type(name, 'Rex');
    await user.selectOptions(screen.getByLabelText(/^Tone/), 'cheery');
    await user.type(screen.getByLabelText('Location'), 'Singapore');
    await user.click(screen.getByRole('button', { name: "Use this browser's time zone" }));
    expect(screen.getByLabelText('Time zone')).toHaveValue(Intl.DateTimeFormat().resolvedOptions().timeZone);
    await user.click(screen.getByRole('button', { name: 'Save persona' }));
    await waitFor(() => expect(hub.data.persona.name).toBe('Rex'));
    expect(hub.data.persona).toMatchObject({ tone: 'cheery', location: 'Singapore' });
    expect(await screen.findByText('Persona saved.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Reset to default' }));
    expect(screen.getByLabelText('Name')).toHaveValue('Reachy');
    expect(screen.getByLabelText(/^Tone/)).toHaveValue('default');
    expect(hub.data.persona.name).toBe('Rex'); // not applied until saved
    expect(await screen.findByText('Default persona loaded — click Save persona to apply.')).toBeInTheDocument();
  });

  it('shows the hub error when the persona is refused', async () => {
    createFakeHub({ status });
    renderApp('#/settings/assistant');
    const user = setup();
    await user.clear(await screen.findByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), ' ');
    await user.click(screen.getByRole('button', { name: 'Save persona' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Request failed (422)');
  });
});

describe('Models tab', () => {
  it('shows the saved key masked only, keeps it when the field is blank, and replaces it when typed', async () => {
    const hub = createFakeHub({ status });
    hub.data.llm.local.api_key = '********2345';
    renderApp('#/settings/models');
    const user = setup();
    expect(await screen.findByText('Saved key: ********2345')).toBeInTheDocument();
    expect(screen.getByLabelText('Base URL')).toHaveValue('http://ovms/v1');
    await user.click(screen.getByRole('button', { name: 'Save model' }));
    await waitFor(() => expect(hub.data.saves).toHaveLength(1));
    expect(hub.data.saves[0]!.body.local).toEqual({ base_url: 'http://ovms/v1', model: 'qwen' }); // no api_key: kept
    expect(await screen.findByText('Model settings saved.')).toBeInTheDocument();

    const field = screen.getAllByLabelText(/^API key/)[0] as HTMLInputElement;
    expect(field.type).toBe('password');
    await user.type(field, 'new-secret-9876');
    await user.click(screen.getByRole('button', { name: 'Save model' }));
    await waitFor(() => expect(hub.data.saves).toHaveLength(2));
    expect(hub.data.saves[1]!.body.local.api_key).toBe('new-secret-9876');
    expect(await screen.findByText('Saved key: ********9876')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('new-secret-9876'); // never shown again
    expect((screen.getAllByLabelText(/^API key/)[0] as HTMLInputElement).value).toBe(''); // the form reset
  });

  it('clears the typed key from the page after saving even when the hub answers with the same masked value', async () => {
    const hub = createFakeHub({ status });
    hub.data.llm.local.api_key = '********9999';
    renderApp('#/settings/models');
    const user = setup();
    const field = () => screen.getAllByLabelText(/^API key/)[0] as HTMLInputElement;
    await screen.findByText('Saved key: ********9999');
    await user.type(field(), 'same-tail-secret-9999'); // masks to the same "********9999" the hub already holds
    await user.click(screen.getByRole('button', { name: 'Save model' }));
    await screen.findByText('Model settings saved.');
    expect(hub.data.saves[0]!.body.local.api_key).toBe('same-tail-secret-9999');
    expect(field().value).toBe('');
    expect(document.body.innerHTML).not.toContain('same-tail-secret-9999');
  });

  it('removes a saved key only when asked', async () => {
    const hub = createFakeHub({ status });
    hub.data.llm.local.api_key = '********2345';
    renderApp('#/settings/models');
    const user = setup();
    await user.click(await screen.findByRole('checkbox', { name: 'Remove saved key' }));
    await user.click(screen.getByRole('button', { name: 'Save model' }));
    await waitFor(() => expect(hub.data.saves[0]!.body.local.api_key).toBeNull());
    expect((await screen.findAllByText('No saved key')).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Saved key: \*/)).not.toBeInTheDocument();
  });

  it('refuses a provider with only a URL or only a model, without sending anything', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/models');
    const user = setup();
    await user.type(await screen.findByLabelText('Cloud base URL'), 'https://c.example/v1');
    await user.click(screen.getByRole('button', { name: 'Save model' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Each provider needs both a URL and model name.');
    expect(hub.data.saves).toHaveLength(0);
  });

  it('suggests a routing when a cloud provider is first added, until the owner chooses', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/models');
    const user = setup();
    await user.type(await screen.findByLabelText('Cloud base URL'), 'https://c.example/v1');
    expect(screen.getByLabelText('Routing')).toHaveValue('local_with_cloud_fallback');
    await user.selectOptions(screen.getByLabelText('Routing'), 'cloud_only');
    await user.type(screen.getByLabelText('Cloud model'), 'big');
    expect(screen.getByLabelText('Routing')).toHaveValue('cloud_only');
    await user.type(screen.getByLabelText('Cloud API key'), 'cloud-key-1111');
    await user.click(screen.getByRole('button', { name: 'Save model' }));
    await waitFor(() => expect(hub.data.saves[0]).toBeDefined());
    expect(hub.data.saves[0]!.body).toMatchObject({ cloud: { base_url: 'https://c.example/v1', model: 'big', api_key: 'cloud-key-1111' }, routing: { mode: 'cloud_only' } });
  });

  it('disables all models', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/models');
    await setup().click(await screen.findByRole('button', { name: 'Disable all models' }));
    await waitFor(() => expect(hub.data.saves[0]!.body).toEqual({ local: null, cloud: null, routing: { mode: 'local_only' } }));
    expect(await screen.findByText('Model disabled.')).toBeInTheDocument();
  });

  it('shows a hub rejection without echoing what was typed', async () => {
    const hub = createFakeHub({ status });
    hub.respond((c) => c === 'PUT /settings/llm', () => jsonResponse({ detail: 'Invalid provider settings' }, 422));
    renderApp('#/settings/models');
    const user = setup();
    await user.type((await screen.findAllByLabelText(/^API key/))[0]!, 'do-not-echo-1');
    await user.click(screen.getByRole('button', { name: 'Save model' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid provider settings');
    expect(document.body.textContent).not.toContain('do-not-echo-1');
  });
});

describe('Web search tab', () => {
  it('saves policy, a provider key and limit; keys are masked afterwards; fallback fields follow the choice', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/search');
    const user = setup();
    await screen.findByLabelText('Policy');
    expect(screen.queryByLabelText('Base URL')).not.toBeInTheDocument(); // built-in SearXNG needs none
    await user.selectOptions(screen.getByLabelText('Policy'), 'auto');
    const brave = within(screen.getByRole('group', { name: 'Brave Search API' }));
    await user.click(brave.getByRole('checkbox', { name: 'Use in rotation' }));
    await user.type(brave.getByLabelText('API key'), 'brave-key-7777');
    await user.clear(brave.getByLabelText('Monthly search limit'));
    await user.type(brave.getByLabelText('Monthly search limit'), '500');
    await user.click(screen.getByRole('button', { name: 'Save web search' }));
    await waitFor(() => expect(hub.data.saves).toHaveLength(1));
    expect(hub.data.saves[0]!.body).toMatchObject({ policy: 'auto', fallback: 'builtin_searxng', base_url: null, api_key: null, result_count: 5 });
    expect(hub.data.saves[0]!.body.hosted.brave).toEqual({ enabled: true, monthly_limit: 500, api_key: 'brave-key-7777' });
    expect(hub.data.saves[0]!.body.hosted.exa).toEqual({ enabled: false, monthly_limit: 900 });
    expect(await screen.findByText('Web search settings saved.')).toBeInTheDocument();
    expect(await screen.findByText('Saved key: ********7777')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('brave-key-7777');

    await user.selectOptions(screen.getByLabelText('Last-resort fallback'), 'searxng');
    expect(screen.getByLabelText('Base URL')).toBeInTheDocument();
  });

  it('shows usage meters and the debug log, with literal text and only http(s) links', async () => {
    const hub = createFakeHub({ status });
    hub.data.searchLog.entries = [
      {
        at: '2030-01-02T07:00:00Z', served_by: 'brave', total_ms: 120, policy: 'auto', query: '<b>weather</b>',
        attempts: [{ provider: 'brave', outcome: 'ok', ms: 100 }],
        results: [{ title: 'Safe', url: 'https://example.com/a', snippet: '<i>s</i>', source_domain: 'example.com' }, { title: 'Bad', url: 'javascript:alert(1)', snippet: 'x', source_domain: 'evil' }],
      },
    ];
    const { container } = renderApp('#/settings/search');
    const user = setup();
    expect(await screen.findByText('This month (2030-01, UTC)')).toBeInTheDocument();
    expect(screen.getByText('3 / 900')).toBeInTheDocument();
    expect(screen.getByText('exa (off)')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open search debug log' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Web search log', hidden: true }));
    expect(await dialog.findByText('<b>weather</b>')).toBeInTheDocument();
    expect(dialog.getByText('Attempts: brave ok (100 ms)')).toBeInTheDocument();
    expect(dialog.getByRole('link', { name: 'Safe' })).toHaveAttribute('href', 'https://example.com/a');
    expect(dialog.queryByRole('link', { name: 'Bad' })).not.toBeInTheDocument();
    expect(container.querySelector('b, i')).toBeNull();
  });

  it('turns web search off with one click', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/search');
    await setup().click(await screen.findByRole('button', { name: 'Turn off web search' }));
    await waitFor(() => expect(hub.data.saves[0]!.body).toEqual({ policy: 'off' }));
    expect(await screen.findByText('Web search turned off.')).toBeInTheDocument();
  });
});
