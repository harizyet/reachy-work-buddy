import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CODING_POLL_MS } from '../src/features/coding/CodingPage';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

const status = { ...SAMPLE_STATUS, default_user_id: 'owner-user', owner_bound: true };
const setup = () => userEvent.setup();
afterEach(() => vi.unstubAllGlobals());

function seeded() {
  const hub = createFakeHub({ status });
  hub.data.coding.projects = [
    { id: 'p1', name: '<b>Reachy</b>', repository_path: '/work/reachy', default_branch: 'main', provider: 'claude-code' },
    { id: 'p2', name: 'Sandbox', repository_path: '/work/sandbox', default_branch: 'dev', provider: 'simulated' },
  ];
  hub.data.coding.sessions = [
    { id: 's1', project_id: 'p1', status: 'waiting_for_input', task_summary: 'Fix <i>tests</i>', started_at: '2030-01-02T07:00:00Z', last_activity_at: '2030-01-02T07:30:00Z', branch: 'fix/tests', last_event: 'asked a question' },
    { id: 's2', project_id: 'p2', status: 'completed', task_summary: 'Done task', started_at: '2030-01-01T07:00:00Z', last_activity_at: '2030-01-01T08:00:00Z', branch: null, last_event: null },
  ];
  return hub;
}

describe('Coding agents', () => {
  it('lists projects and sessions with status wording, all literal; only active sessions can be refreshed or stopped', async () => {
    seeded();
    const { container } = renderApp('#/coding');
    expect(await screen.findByText('<b>Reachy</b> — /work/reachy (main, claude-code)')).toBeInTheDocument();
    expect(screen.getByText('<b>Reachy</b> — waiting for input')).toBeInTheDocument();
    expect(screen.getByText('Fix <i>tests</i>')).toBeInTheDocument();
    expect(screen.getByText('asked a question')).toBeInTheDocument();
    expect(container.querySelector('b, i')).toBeNull();
    const cards = screen.getAllByText(/ — (waiting for input|completed)$/).map((e) => e.closest('div')!);
    expect(within(cards[0]!).getByRole('button', { name: 'Stop' })).toBeInTheDocument();
    expect(within(cards[0]!).getByRole('button', { name: 'Refresh status' })).toBeInTheDocument();
    expect(within(cards[1]!).queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument();
  });

  it('shows the Claude allowance, live or last reported, or explains how to get one', async () => {
    const hub = seeded();
    hub.data.coding.allowance = { source: 'live', windows: [{ name: 'five_hour', value: 42, unit: '%', resets_at: '2030-01-02T12:00:00Z' }] };
    renderApp('#/coding');
    expect(await screen.findByText('Live from your Claude account')).toBeInTheDocument();
    expect(screen.getByText(/five hour: 42 % \(resets /)).toBeInTheDocument();
  });

  it('explains when there is no allowance reading', async () => {
    seeded();
    renderApp('#/coding');
    expect(await screen.findByText(/No allowance reading available\. Save a Claude account usage credential/)).toBeInTheDocument();
  });

  it('adds a project with the default branch main', async () => {
    const hub = seeded();
    renderApp('#/coding');
    const user = setup();
    await user.type(await screen.findByLabelText('Name'), 'New repo');
    await user.type(screen.getByLabelText('Repository path (on the robot host)'), '/work/new');
    await user.selectOptions(screen.getByLabelText('Provider'), 'simulated');
    await user.click(screen.getByRole('button', { name: 'Add project' }));
    expect(await screen.findByText('Project added.')).toBeInTheDocument();
    expect(hub.data.coding.projects.at(-1)).toMatchObject({ name: 'New repo', repository_path: '/work/new', default_branch: 'main', provider: 'simulated' });
  });

  it('asks before starting a session, warning when it spends usage; Cancel starts nothing', async () => {
    const hub = seeded();
    renderApp('#/coding');
    const user = setup();
    await user.type(await screen.findByLabelText('Task'), 'Refactor the parser');
    await user.type(screen.getByLabelText('Branch (optional)'), 'feat/parser');
    await user.click(screen.getByRole('button', { name: 'Start session' }));
    let dialog = within(await screen.findByRole('dialog', { name: 'Start a coding session?', hidden: true }));
    expect(dialog.getByText(/Start a coding session on "<b>Reachy<\/b>"\? This spends Claude usage, and with an API key it can change files in the repository\./)).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Cancel' }));
    expect(hub.data.coding.starts).toHaveLength(0);

    await user.type(screen.getByLabelText('Task'), 'Refactor the parser');
    await user.click(screen.getByRole('button', { name: 'Start session' }));
    dialog = within(await screen.findByRole('dialog', { name: 'Start a coding session?', hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Start session' }));
    await waitFor(() => expect(hub.data.coding.starts).toEqual([{ project_id: 'p1', task_summary: 'Refactor the parser', branch: null }]));
    expect(await screen.findByText('Session started.')).toBeInTheDocument();
  });

  it('a simulated project starts without the spending warning; with no project it says to add one', async () => {
    const hub = seeded();
    renderApp('#/coding');
    const user = setup();
    await screen.findByRole('option', { name: 'Sandbox' });
    await user.selectOptions(screen.getByLabelText('Project'), 'p2');
    await user.type(screen.getByLabelText('Task'), 'Dry run');
    await user.click(screen.getByRole('button', { name: 'Start session' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Start a coding session?', hidden: true }));
    expect(dialog.getByText('Start a coding session on "Sandbox"?')).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Cancel' }));

    hub.data.coding.projects = [];
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    await screen.findByText('No projects yet. Add one below.');
    await user.type(screen.getByLabelText('Task'), 'x');
    await user.click(screen.getByRole('button', { name: 'Start session' }));
    expect(await screen.findByText('Add a project first.')).toBeInTheDocument();
  });

  it('stops a session only after confirmation', async () => {
    const hub = seeded();
    renderApp('#/coding');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Stop' }));
    let dialog = within(await screen.findByRole('dialog', { name: 'Stop this coding session?', hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Cancel' }));
    expect(hub.calls.some((c) => c.endsWith('/stop'))).toBe(false);
    await user.click(screen.getByRole('button', { name: 'Stop' }));
    dialog = within(await screen.findByRole('dialog', { name: 'Stop this coding session?', hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Stop' }));
    await waitFor(() => expect(hub.calls).toContain('POST /coding-agents/sessions/s1/stop'));
    expect(await screen.findByText(/ — stopped$/)).toBeInTheDocument();
  });

  it('toggles events and usage per session', async () => {
    const hub = seeded();
    hub.data.coding.events.s1 = [{ timestamp: '2030-01-02T07:10:00Z', type: 'tool_call', summary: 'ran <b>tests</b>' }];
    hub.data.coding.usage.s1 = [{ name: 'input_tokens', value: 1200, unit: 'tokens', resets_at: null }];
    renderApp('#/coding');
    const user = setup();
    const card = within((await screen.findByText(/<b>Reachy<\/b> — waiting for input/)).closest('div')!);
    await user.click(card.getByRole('button', { name: 'Events' }));
    expect(await card.findByText(/tool call · ran <b>tests<\/b>/)).toBeInTheDocument();
    await user.click(card.getByRole('button', { name: 'Usage' }));
    expect(await card.findByText('input tokens: 1200 tokens')).toBeInTheDocument();
    await user.click(card.getByRole('button', { name: 'Usage' }));
    expect(card.queryByText('input tokens: 1200 tokens')).not.toBeInTheDocument();
  });

  it('lists terminal sessions as view-only, and explains when none are found', async () => {
    const hub = seeded();
    hub.data.coding.terminal = [{ session_id: 't1', title: 'Fix build', active: true, project_path: '/home/me/app', git_branch: 'main', last_activity_at: '2030-01-02T07:00:00Z', last_prompt: 'why does it fail?' }];
    renderApp('#/coding');
    expect(await screen.findByText('Active — Fix build')).toBeInTheDocument();
    expect(screen.getByText('Last prompt: why does it fail?')).toBeInTheDocument();
    expect(screen.getByText(/shown for monitoring only/)).toBeInTheDocument();
  });

  it('shows an unavailable service plainly', async () => {
    const hub = createFakeHub({ status });
    hub.respond((c) => c.startsWith('GET /coding-agents/'), () => jsonResponse({ detail: 'Coding agent service unavailable' }, 502));
    renderApp('#/coding');
    expect(await screen.findByText('Coding agent service unavailable')).toBeInTheDocument();
    expect(screen.getByText('Allowance unavailable: Coding agent service unavailable')).toBeInTheDocument();
  });
});

describe('Coding agents polling', () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'], shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it('refreshes while the page is open and stops when it is left', async () => {
    const hub = seeded();
    renderApp('#/coding');
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTimeAsync(ms) });
    await screen.findByText('<b>Reachy</b> — waiting for input');
    const count = () => hub.calls.filter((c) => c === 'GET /coding-agents/sessions').length;
    const first = count();
    await act(async () => { await vi.advanceTimersByTimeAsync(CODING_POLL_MS + 200); });
    expect(count()).toBeGreaterThan(first);
    await user.click(screen.getByRole('link', { name: 'Overview' }));
    const left = count();
    await act(async () => { await vi.advanceTimersByTimeAsync(CODING_POLL_MS * 3); });
    expect(count()).toBe(left);
  });
});
