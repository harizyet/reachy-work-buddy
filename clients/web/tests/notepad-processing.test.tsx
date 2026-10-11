import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

// Phase 49 in the Notepad: the checkbox, the status, the review section, and meeting links. The fake server here follows the contract pinned by the real-chain tests in
// services/companion-core/tests/test_notepad_processing.py and services/reachy-hub/tests/test_notepad_processing_hub.py; the real browser run is e2e/notepad.spec.ts.

const ISO = '2030-03-05T15:00:00Z';
type Proposal = Record<string, any>;
const proposal = (over: Record<string, unknown> = {}): Proposal => ({
  id: 'p1', note_id: 'n1', kind: 'task', status: 'pending', text: 'Renew the lab safety certificate', evidence: 'Renew the lab safety certificate before it lapses.',
  sources: [{ kind: 'note', quote: 'Renew the lab safety certificate before it lapses.', meeting_id: null, title: null, speaker: null }], evidence_from: 'note',
  stated_time: null, due_at: null, ambiguity: [], source_changed: false, record_kind: null, record_id: null, edited: false, ...over,
});

function setup(options: { enabled?: boolean; state?: string; proposals?: Proposal[]; links?: unknown[]; job?: Record<string, unknown> | null } = {}) {
  const hub = createFakeHub({ status: SAMPLE_STATUS, notes: [{ id: 'n1', title: 'Tasks for next week', body: 'Renew the lab safety certificate before it lapses.', updated_at: new Date().toISOString() }] });
  const base = globalThis.fetch;
  const server = {
    state: options.state ?? 'not_processed', proposals: options.proposals ?? [], links: options.links ?? [], job: options.job ?? null as Record<string, unknown> | null, calls: [] as { call: string; body: any }[],
  };
  const view = () => ({ note_id: 'n1', state: server.state, job: server.job, note_changed_since_job: false, proposals: server.proposals });
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://hub.test');
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    const call = `${method} ${url.pathname}`;
    if (url.pathname === '/notepad-processing/config') return jsonResponse({ enabled: options.enabled ?? true });
    if (!url.pathname.startsWith('/notes/') && !url.pathname.startsWith('/notepad-')) return base(input, init);
    server.calls.push({ call, body });
    if (call === 'GET /notes/n1/processing') return jsonResponse(view());
    if (call === 'POST /notes/n1/processing') { server.state = 'queued'; server.job = { id: 'j1', status: 'queued', error: null, model: null, proposal_count: 0, meetings: [] }; return jsonResponse({ created: true, ...view() }); }
    if (call === 'POST /notepad-processing/jobs/j1/retry') { server.state = 'queued'; return jsonResponse(view()); }
    if (call === 'GET /notes/n1/meeting-links') return jsonResponse({ note_id: 'n1', links: server.links });
    const link = url.pathname.match(/^\/notes\/n1\/meeting-links\/(.+)$/);
    if (link && method === 'PUT') {
      server.links = body.state === 'confirmed'
        ? [{ id: 'l1', meeting_id: link[1], source: 'explicit', state: 'confirmed', title_match: false, meeting_missing: false, meeting: { id: link[1], title: 'Weekly sync', started_at: ISO, transcript_ready: true } }]
        : [];
      return jsonResponse({ note_id: 'n1', links: server.links });
    }
    const act = url.pathname.match(/^\/notepad-proposals\/(.+)\/(accept|dismiss)$/);
    if (act) {
      server.proposals = server.proposals.map((p) => (p.id === act[1] ? { ...p, status: act[2] === 'accept' ? 'accepted' : 'dismissed', record_kind: act[2] === 'accept' ? 'task' : null, record_id: act[2] === 'accept' ? 'r1' : null } : p));
      return jsonResponse({ proposal: server.proposals.find((p) => p.id === act[1]), record: act[2] === 'accept' ? { kind: 'task', id: 'r1' } : null });
    }
    return jsonResponse({ detail: 'Not Found' }, 404);
  }));
  return { hub, server };
}

afterEach(() => vi.unstubAllGlobals());

async function openNote() {
  const user = userEvent.setup();
  renderApp('#/notes');
  await user.click(await screen.findByRole('button', { name: /Tasks for next week/ }));
  return user;
}

describe('Processed icon', () => {
  it.each([
    ['review_required', 'Processed by Reachy: suggestions waiting for your review'],
    ['completed', 'Processed by Reachy'],
    ['queued', 'Waiting to be processed by Reachy'],
    ['processing', 'Being processed by Reachy'],
    ['failed', 'Reachy could not process this note'],
  ])('marks a %s note in the list and in the open note', async (state, label) => {
    setup({ state, job: { id: 'j1', status: 'succeeded', error: null, model: 'm', proposal_count: 0, meetings: [] } });
    const user = await openNote();
    void user;
    await waitFor(() => expect(screen.getAllByRole('img', { name: label }).length).toBeGreaterThanOrEqual(2)); // the list row and the editor header
    expect(screen.getByRole('button', { name: /Tasks for next week/ })).toContainElement(screen.getAllByTestId('processed-icon')[0]!);
  });

  it('shows no mark for a note that was never sent', async () => {
    setup({ state: 'not_processed' });
    await openNote();
    await screen.findByRole('status', { name: 'Processing status' });
    await waitFor(() => expect(screen.getByRole('status', { name: 'Processing status' })).toHaveTextContent('Not processed'));
    expect(screen.queryByTestId('processed-icon')).not.toBeInTheDocument();
  });

  it('shows no mark when the feature is off', async () => {
    setup({ enabled: false, state: 'completed' });
    renderApp('#/notes');
    await screen.findByRole('button', { name: /Tasks for next week/ });
    expect(screen.queryByTestId('processed-icon')).not.toBeInTheDocument();
  });
});

describe('Notepad processing', () => {
  it('shows no error text when nothing has failed (regression: found in the first production run)', async () => {
    setup({ state: 'review_required', proposals: [proposal()], links: [{ id: 'l1', meeting_id: 'm1', source: 'explicit', state: 'confirmed', title_match: false, meeting_missing: false, meeting: { id: 'm1', title: 'Weekly sync', started_at: ISO, transcript_ready: true } }] });
    await openNote();
    await screen.findByLabelText('Suggestions from Reachy');
    expect(screen.queryByText(/something went wrong/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows nothing when the feature is off, so the Notepad is exactly as before', async () => {
    setup({ enabled: false });
    await openNote();
    expect(screen.queryByText('Send to Reachy for processing')).not.toBeInTheDocument();
  });

  it('starts unchecked and says the note is not processed; ticking it saves then sends the saved text once', async () => {
    const { server } = setup();
    const user = await openNote();
    const box = await screen.findByRole('checkbox', { name: 'Send to Reachy for processing' });
    expect(box).not.toBeChecked();
    await waitFor(() => expect(screen.getByRole('status', { name: 'Processing status' })).toHaveTextContent('Not processed'));
    await user.click(box);
    await waitFor(() => expect(server.calls.filter((c) => c.call === 'POST /notes/n1/processing')).toHaveLength(1));
    const sent = server.calls.find((c) => c.call === 'POST /notes/n1/processing')!.body;
    expect(sent.expected_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(sent.force).toBe(false);
    await waitFor(() => expect(screen.getByRole('status', { name: 'Processing status' })).toHaveTextContent('Queued'));
    await waitFor(() => expect(box).not.toBeChecked()); // one-shot: another run is an explicit action
  });

  it.each([
    ['queued', 'Queued'], ['processing', 'Processing'], ['review_required', 'Review required'], ['completed', 'Completed'], ['failed', 'Failed'],
  ])('shows the %s state', async (state, label) => {
    setup({ state, job: { id: 'j1', status: 'queued', error: state === 'failed' ? 'model_unavailable' : null, model: null, proposal_count: 0, meetings: [] } });
    await openNote();
    await waitFor(() => expect(screen.getByRole('status', { name: 'Processing status' })).toHaveTextContent(label));
  });

  it('offers a retry for a failed job and explains the failure without any note text', async () => {
    const { server } = setup({ state: 'failed', job: { id: 'j1', status: 'failed', error: 'model_unavailable', model: null, proposal_count: 0, meetings: [] } });
    const user = await openNote();
    expect(await screen.findByText('The local model was not available.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(server.calls.some((c) => c.call === 'POST /notepad-processing/jobs/j1/retry')).toBe(true));
  });

  it('draws suggestions apart from real tasks, with the supporting text and where it came from', async () => {
    setup({ state: 'review_required', proposals: [proposal({ ambiguity: ['which day is unclear'] })] });
    await openNote();
    const box = await screen.findByLabelText('Suggestions from Reachy');
    expect(within(box).getByText(/Not yet confirmed/)).toBeInTheDocument();
    expect(within(box).getByText('Renew the lab safety certificate')).toBeInTheDocument();
    expect(within(box).getByText(/“Renew the lab safety certificate before it lapses\.”/)).toBeInTheDocument();
    expect(within(box).getByText('From the note')).toBeInTheDocument();
    expect(within(box).getByText('which day is unclear')).toBeInTheDocument();
  });

  it('labels transcript evidence with the meeting and the speaker label, and both when both support it', async () => {
    setup({ state: 'review_required', proposals: [proposal({ evidence_from: 'both', sources: [
      { kind: 'note', quote: 'Chase the vendor.', meeting_id: null, title: null, speaker: null },
      { kind: 'meeting', quote: 'I will send the purchase order.', meeting_id: 'm1', title: 'Weekly sync', speaker: 'Speaker 2' },
    ] })] });
    await openNote();
    expect(await screen.findByText('From the note and a meeting transcript')).toBeInTheDocument();
    expect(screen.getByText(/Meeting “Weekly sync”, Speaker 2/)).toBeInTheDocument();
    expect(screen.getByText('Your note')).toBeInTheDocument();
  });

  it('accepts, and the accepted item moves out of the suggestions', async () => {
    const { server } = setup({ state: 'review_required', proposals: [proposal()] });
    const user = await openNote();
    await user.click(await screen.findByRole('button', { name: 'Accept' }));
    await waitFor(() => expect(server.calls.some((c) => c.call === 'POST /notepad-proposals/p1/accept')).toBe(true));
    expect(server.calls.find((c) => c.call === 'POST /notepad-proposals/p1/accept')!.body).toEqual({});
    await waitFor(() => expect(screen.queryByLabelText('Suggestions from Reachy')).not.toBeInTheDocument());
    expect(await screen.findByText(/Added from this note/)).toHaveTextContent('Task “Renew the lab safety certificate”');
  });

  it('edits then accepts with the changed text; a reminder without a time cannot be accepted', async () => {
    const { server } = setup({ state: 'review_required', proposals: [proposal({ id: 'p2', kind: 'reminder', text: 'Call the bank' })] });
    const user = await openNote();
    expect(await screen.findByRole('button', { name: 'Accept' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Edit and accept' }));
    await user.selectOptions(screen.getByLabelText('Add as'), 'task');
    const field = screen.getByLabelText('Proposed text');
    await user.clear(field);
    await user.type(field, 'Phone the bank');
    await user.click(screen.getByRole('button', { name: 'Save and accept' }));
    await waitFor(() => expect(server.calls.some((c) => c.call === 'POST /notepad-proposals/p2/accept')).toBe(true));
    expect(server.calls.find((c) => c.call === 'POST /notepad-proposals/p2/accept')!.body).toEqual({ text: 'Phone the bank', kind: 'task' });
  });

  it('dismisses without adding anything', async () => {
    const { server } = setup({ state: 'review_required', proposals: [proposal()] });
    const user = await openNote();
    await user.click(await screen.findByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(server.calls.some((c) => c.call === 'POST /notepad-proposals/p1/dismiss')).toBe(true));
    await waitFor(() => expect(screen.queryByLabelText('Suggestions from Reachy')).not.toBeInTheDocument());
    expect(screen.queryByText(/Added from this note/)).not.toBeInTheDocument();
  });

  it('renders model and note text literally', async () => {
    const { server } = setup({ state: 'review_required', proposals: [proposal({ text: '<img src=x onerror=boom()> do it' })] });
    void server;
    await openNote();
    expect(await screen.findByText('<img src=x onerror=boom()> do it')).toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull();
  });

  it('lists information that stays in the note, without a decision to make', async () => {
    setup({ state: 'completed', proposals: [proposal({ id: 'p9', kind: 'reference', status: 'noted', text: 'Lab wifi password rotates monthly' })] });
    await openNote();
    expect(await screen.findByText('Information that stays in the note (1)')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument();
  });

  it('shows a suggested meeting link, confirms it, and unlinks it', async () => {
    const { server } = setup({ links: [{ id: 'l1', meeting_id: 'm1', source: 'temporal', state: 'suggested', title_match: false, meeting_missing: false, meeting: { id: 'm1', title: 'Weekly sync', started_at: ISO, transcript_ready: false } }] });
    const user = await openNote();
    expect(await screen.findByText('Taken during this meeting?', { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/transcript not ready/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Link' }));
    await waitFor(() => expect(server.calls.find((c) => c.call === 'PUT /notes/n1/meeting-links/m1')?.body).toEqual({ state: 'confirmed' }));
    expect(await screen.findByText('Linked to', { exact: false })).toBeInTheDocument();
    expect(await screen.findByRole('checkbox', { name: /Also use the linked meeting transcript/ })).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Unlink' }));
    await waitFor(() => expect(server.calls.filter((c) => c.call === 'PUT /notes/n1/meeting-links/m1').at(-1)?.body).toEqual({ state: 'rejected' }));
  });

  it('sends include_meetings only when the owner ticks the transcript box', async () => {
    const { server } = setup({ links: [{ id: 'l1', meeting_id: 'm1', source: 'explicit', state: 'confirmed', title_match: false, meeting_missing: false, meeting: { id: 'm1', title: 'Weekly sync', started_at: ISO, transcript_ready: true } }] });
    const user = await openNote();
    await user.click(await screen.findByRole('checkbox', { name: /Also use the linked meeting transcript/ }));
    await user.click(screen.getByRole('checkbox', { name: 'Send to Reachy for processing' }));
    await waitFor(() => expect(server.calls.find((c) => c.call === 'POST /notes/n1/processing')?.body.include_meetings).toBe(true));
  });

  it('tells the owner when a linked transcript was not used', async () => {
    setup({ state: 'completed', job: { id: 'j1', status: 'succeeded', error: null, model: 'm', proposal_count: 1, meetings: [{ meeting_id: 'm1', title: 'Weekly sync', included: false, reason: 'the transcript is not ready yet' }] } });
    await openNote();
    expect(await screen.findByText(/The transcript of “Weekly sync” was not used: the transcript is not ready yet/)).toBeInTheDocument();
  });
});
