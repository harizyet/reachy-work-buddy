import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

// Phase 31 on the meeting page: the Analysis tab, the review of action candidates and their evidence. The fake server follows the contract pinned by the real-chain tests in
// services/companion-core/tests/test_meeting_analysis.py and services/reachy-hub/tests/test_meeting_analysis_hub.py; the real browser run is the owner's acceptance.

type Item = Record<string, any>;
const evidence = (over: Record<string, unknown> = {}) => ({ segment: 3, start: 185, end: 190, speaker: 'Speaker 2', quote: 'Alice will contact the vendor by Friday', in_gap: false, ...over });
const item = (over: Item = {}): Item => ({
  id: 'i1', meeting_id: 'm1', kind: 'action', status: 'pending', text: 'Contact the vendor', evidence: [evidence()], assignee: 'Alice', stated_time: 'by Friday',
  ambiguity: ['a time was suggested that the quote does not state; it was dropped'], support: 'stated', source_changed: false, task_text: 'Alice: Contact the vendor (by Friday)', record_id: null, edited: false, ...over,
});

function setup(options: { enabled?: boolean; state?: string; items?: Item[]; run?: Record<string, unknown> | null } = {}) {
  const hub = createFakeHub({ status: { ...SAMPLE_STATUS, default_user_id: 'owner-user', owner_bound: true }, meetings: [{
    id: 'm1', title: 'Weekly sync', status: 'complete', created_at: '2030-01-02T07:00:00Z', project_scope: null, participants: [], context: null, duration_seconds: 300,
    transcript_segments: [{ start: 0, end: 3, text: 'hello' }], diarization_segments: [], aligned_segments: [{ speaker: 'speaker_0' }], audio_gaps: null,
  }] });
  const base = globalThis.fetch;
  const server = { state: options.state ?? 'not_analysed', items: options.items ?? [], run: options.run ?? null as Record<string, unknown> | null, calls: [] as { call: string; body: any }[] };
  const view = () => ({ meeting_id: 'm1', state: server.state, run: server.run, transcript_changed_since_run: false, items: server.items });
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://hub.test');
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    const call = `${method} ${url.pathname}`;
    if (url.pathname === '/meeting-analysis/config') return jsonResponse({ enabled: options.enabled ?? true });
    if (!url.pathname.startsWith('/meeting-analysis/') && !url.pathname.endsWith('/analysis')) return base(input, init);
    server.calls.push({ call, body });
    if (call === 'GET /meetings/m1/analysis') return jsonResponse(view());
    if (call === 'POST /meetings/m1/analysis') { server.state = 'queued'; server.run = { id: 'r1', status: 'queued', error: null, model: null, item_count: 0, rejected: {}, transcript_hash: 'h' }; return jsonResponse({ created: true, ...view() }); }
    if (call === 'POST /meeting-analysis/runs/r1/retry') { server.state = 'queued'; return jsonResponse(view()); }
    const act = url.pathname.match(/^\/meeting-analysis\/items\/(.+)\/(accept|dismiss)$/);
    if (act) {
      server.items = server.items.map((i) => (i.id === act[1] ? { ...i, status: act[2] === 'accept' ? 'accepted' : 'dismissed', record_id: act[2] === 'accept' ? 'r9' : null, task_text: body?.text ?? i.task_text } : i));
      return jsonResponse({ item: server.items.find((i) => i.id === act[1]), record: act[2] === 'accept' ? { kind: 'task', id: 'r9' } : null });
    }
    return jsonResponse({ detail: 'Not Found' }, 404);
  }));
  return { hub, server };
}

afterEach(() => vi.unstubAllGlobals());

async function openAnalysis() {
  const user = userEvent.setup();
  renderApp('#/meetings/m1');
  await user.click(await screen.findByRole('button', { name: 'Analysis' }));
  return user;
}

describe('Meeting analysis tab', () => {
  it('is absent when the feature is off', async () => {
    setup({ enabled: false });
    renderApp('#/meetings/m1');
    await screen.findByRole('button', { name: 'Summary' });
    expect(screen.queryByRole('button', { name: 'Analysis' })).not.toBeInTheDocument();
  });

  it('starts an analysis, shows the queued state and sends nothing that makes a task', async () => {
    const { server } = setup();
    const user = await openAnalysis();
    await waitFor(() => expect(screen.getByRole('status', { name: 'Analysis status' })).toHaveTextContent('Not analysed'));
    await user.click(screen.getByRole('button', { name: 'Analyse this meeting' }));
    await waitFor(() => expect(screen.getByRole('status', { name: 'Analysis status' })).toHaveTextContent('Queued'));
    expect(server.calls.map((c) => c.call)).toContain('POST /meetings/m1/analysis');
    expect(server.calls.some((c) => c.call.includes('/accept'))).toBe(false);
  });

  it('shows actions apart from tasks, with evidence, timestamp, assignee and ambiguity; text is literal', async () => {
    setup({ state: 'review_required', run: { id: 'r1', status: 'succeeded', error: null, model: 'm', item_count: 1, rejected: { no_evidence_in_source: 2 }, transcript_hash: 'h' },
      items: [item({ text: 'Contact <b>the vendor</b>' })] });
    const container = document.body;
    await openAnalysis();
    const review = await screen.findByLabelText('Actions from this meeting');
    expect(within(review).getByText('Contact <b>the vendor</b>')).toBeInTheDocument();
    expect(container.querySelector('b')).toBeNull();
    expect(within(review).getByText('“Alice will contact the vendor by Friday”')).toBeInTheDocument();
    expect(within(review).getByRole('button', { name: 'Play from 3:05' })).toBeInTheDocument();
    expect(within(review).getByText(/Not yet confirmed. Nothing is added to your tasks/)).toBeInTheDocument();
    expect(within(review).getByText('a time was suggested that the quote does not state; it was dropped')).toBeInTheDocument();
    expect(screen.getByText('2 suggestions were left out because the transcript did not support them.')).toBeInTheDocument();
  });

  it('confirms an action, with an edit when asked, and dismisses another', async () => {
    const { server } = setup({ state: 'review_required', items: [item(), item({ id: 'i2', text: 'Update the schedule', task_text: 'Update the schedule', assignee: null, stated_time: null })] });
    const user = await openAnalysis();
    const first = (await screen.findByText('Contact the vendor')).closest('li')!;
    await user.click(within(first).getByRole('button', { name: 'Edit and confirm' }));
    const box = within(first).getByLabelText('Task text');
    await user.clear(box);
    await user.type(box, 'Alice: contact the vendor about licensing');
    await user.click(within(first).getByRole('button', { name: 'Save and confirm' }));
    await waitFor(() => expect(server.calls.find((c) => c.call === 'POST /meeting-analysis/items/i1/accept')?.body).toEqual({ text: 'Alice: contact the vendor about licensing' }));
    const second = (await screen.findByText('Update the schedule')).closest('li')!;
    expect(within(second).getByText(/It would be added as: “Update the schedule”/)).toBeInTheDocument();
    await user.click(within(second).getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(server.calls.map((c) => c.call)).toContain('POST /meeting-analysis/items/i2/dismiss'));
    await waitFor(() => expect(screen.getByText(/Added to your tasks: “Alice: contact the vendor about licensing”/)).toBeInTheDocument());
    expect(server.calls.filter((c) => c.call.endsWith('/accept'))).toHaveLength(1);
  });

  it('plain confirm sends no text, and decisions and open questions are listed with their evidence and can be dismissed', async () => {
    const { server } = setup({ state: 'review_required', items: [
      item(),
      item({ id: 'd1', kind: 'decision', status: 'noted', text: 'Migrate in November', evidence: [evidence({ segment: 2, start: 120, quote: 'we will migrate in November' })], assignee: null, stated_time: null, ambiguity: [], task_text: null }),
      item({ id: 'q1', kind: 'open_question', status: 'noted', text: 'Who owns the backup budget', evidence: [evidence({ segment: 5, start: 300, in_gap: true, quote: 'nobody knows who owns the budget' })], assignee: null, stated_time: null, ambiguity: [], task_text: null }),
    ] });
    const user = await openAnalysis();
    expect(within(await screen.findByLabelText('Decisions')).getByText('Migrate in November')).toBeInTheDocument();
    const questions = screen.getByLabelText('Open questions');
    expect(within(questions).getByText(/recorded in a stretch with no audio/)).toBeInTheDocument();
    await user.click(within(questions).getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(server.calls.map((c) => c.call)).toContain('POST /meeting-analysis/items/q1/dismiss'));
    await user.click(screen.getByRole('button', { name: 'Confirm as task' }));
    await waitFor(() => expect(server.calls.find((c) => c.call === 'POST /meeting-analysis/items/i1/accept')?.body).toEqual({}));
  });

  it('marks items whose quote may not support them, and only those', async () => {
    setup({ state: 'review_required', items: [
      item({ id: 'i3', text: 'Weak action', support: 'uncertain' }),
      item({ id: 'd2', kind: 'decision', status: 'noted', text: 'Weak decision', support: 'uncertain', task_text: null, assignee: null, stated_time: null, ambiguity: [] }),
      item({ id: 'd3', kind: 'decision', status: 'noted', text: 'Solid decision', support: 'stated', task_text: null, assignee: null, stated_time: null, ambiguity: [] }),
    ] });
    await openAnalysis();
    expect(await screen.findAllByText('Check the quote')).toHaveLength(2);
    expect(within(screen.getByText('Solid decision').closest('li')!).queryByText('Check the quote')).not.toBeInTheDocument();
  });

  it('shows a failure with a retry and the fixed wording for the code', async () => {
    const { server } = setup({ state: 'failed', run: { id: 'r1', status: 'failed', error: 'model_unavailable', model: null, item_count: 0, rejected: {}, transcript_hash: 'h' } });
    const user = await openAnalysis();
    expect(await screen.findByText('The local model was not available.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(server.calls.map((c) => c.call)).toContain('POST /meeting-analysis/runs/r1/retry'));
  });

  it('says so when a finished analysis found nothing', async () => {
    setup({ state: 'completed', run: { id: 'r1', status: 'succeeded', error: null, model: 'm', item_count: 0, rejected: {}, transcript_hash: 'h' } });
    await openAnalysis();
    expect(await screen.findByText('Nothing in this transcript was clear enough to list.')).toBeInTheDocument();
  });
});
