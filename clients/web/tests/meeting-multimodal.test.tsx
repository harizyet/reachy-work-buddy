import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

// Phase 53 on the meeting page: attached documents, page estimates beside the transcript with their certainty, the owner's corrections, questions across both sources and combined findings.
// The fake server follows the contract pinned by the real-chain tests in services/companion-core/tests/test_meeting_multimodal*.py and services/reachy-hub/tests/test_meeting_multimodal_hub.py;
// the real browser run is the owner's acceptance.

type Obj = Record<string, any>;
const NOW = '2030-01-02T07:00:00Z';
const libraryDoc = (id: string, title: string): Obj => ({
  id, title, filename: `${id}.pdf`, mime_type: 'application/pdf', size_bytes: 2048, source_hash: 'ab'.repeat(32), sensitivity: 'work-private', project_scope: null, state: 'ready',
  processing_priority: 'background', tier: 'basic', page_count: 6, error_code: null, next_tier: 'standard', created_at: NOW, updated_at: NOW,
});
const attached = (over: Obj = {}): Obj => ({ document_id: 'd1', title: 'Edge Platform Review', filename: 'edge.pdf', state: 'ready', ready: true, page_count: 6, tier: 'basic', sensitivity: 'work-private', project_scope: null, error_code: null, ...over });
const suggestion = (over: Obj = {}): Obj => ({
  document_id: 'd1', document_title: 'Edge Platform Review', page: 2, slide_title: 'Edge Architecture', certainty: 'high', method: 'semantic', relation: 'supports',
  reason: 'Shares these words with the page: inference, control, plane.', model_note: null, shared_terms: ['inference'], explicit_refs: [], contradictions: [], alternatives: [], ...over,
});
const shown = (over: Obj = {}): Obj => ({ document_id: 'd1', document_title: 'Edge Platform Review', page: 2, slide_title: 'Edge Architecture', authority: 'suggested', certainty: 'high', ...over });
const win = (over: Obj = {}): Obj => ({
  window_key: '0-0', segment_ids: [0], start: 0, end: 8, suggestion: suggestion(), owner: null, review_status: 'suggested', shown: shown(), source_changed: false, document_changed: false, stale: false, ...over,
});
const overview = (over: Obj = {}): Obj => ({
  meeting_id: 'm1', sensitivity: 'work-private', documents: [attached()], transcript_hash: 'h',
  alignment: { state: 'succeeded', run: { id: 'r1', status: 'succeeded', error: null, model: 'm', stats: {} }, transcript_changed: false, documents_changed: false, documents_added: false },
  analysis: { state: 'not_run', run: null, items: [] }, windows: [win(), win({ window_key: '1-1', segment_ids: [1], start: 20, end: 28, suggestion: null, shown: null, review_status: 'suggested' })],
  unaddressed: [{ document_id: 'd1', document_title: 'Edge Platform Review', page: 5 }], disclaimer: 'Which page was discussed is an estimate.', ...over,
});
const finding = (over: Obj = {}): Obj => ({
  id: 'f1', kind: 'action', status: 'pending', text: 'Own certificate rotation', evidence: [{ source: 'transcript', quote: 'Priya will own certificate rotation', segment: 1, start: 20, speaker: 'Speaker 2', document_id: null, page: null },
  { source: 'document', quote: 'Certificate rotation', segment: null, start: null, speaker: null, document_id: 'd1', page: 5 }], assignee: 'Priya', stated_time: 'by Friday', ambiguity: ['who this was assigned to is not stated'],
  support: 'stated', sensitivity: 'work-private', source_changed: false, document_changed: false, task_text: 'Priya: Own certificate rotation (by Friday)', record_id: null, ...over,
});

function setup(options: { enabled?: boolean; data?: Obj; answer?: Obj } = {}) {
  const hub = createFakeHub({ status: { ...SAMPLE_STATUS, default_user_id: 'owner-user', owner_bound: true }, meetings: [{
    id: 'm1', title: 'Weekly sync', status: 'complete', created_at: NOW, project_scope: null, participants: [], context: null, duration_seconds: 300,
    transcript_segments: [{ start: 0, end: 8, text: 'The control plane is separate.' }, { start: 20, end: 28, text: 'Priya will own certificate rotation.' }], diarization_segments: [],
    aligned_segments: [{ speaker: 'speaker_0' }, { speaker: 'speaker_1' }], audio_gaps: null,
  }] });
  const base = globalThis.fetch;
  const server = { data: options.data ?? overview(), calls: [] as { call: string; body: any }[] };
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://hub.test');
    const method = init?.method ?? 'GET';
    const body = init?.body && !(init.body instanceof FormData) ? JSON.parse(String(init.body)) : undefined;
    const call = `${method} ${url.pathname}`;
    if (url.pathname === '/meeting-multimodal/config') return jsonResponse({ enabled: options.enabled ?? true });
    if (url.pathname === '/document-library/config') return jsonResponse({ enabled: true });
    if (url.pathname === '/document-library/documents' && method === 'GET') return jsonResponse([libraryDoc('d1', 'Edge Platform Review'), libraryDoc('d2', 'Cost deck')]);
    if (url.pathname.endsWith('/image')) return new Response(new Blob(['x'], { type: 'image/png' }), { status: 404 });
    if (!url.pathname.includes('multimodal')) return base(input, init);
    server.calls.push({ call, body });
    if (call === 'GET /meetings/m1/multimodal') return jsonResponse(server.data);
    if (call === 'POST /meetings/m1/multimodal/attachments') return jsonResponse({ created: true, document: attached({ document_id: body.document_id }) });
    if (call.startsWith('DELETE /meetings/m1/multimodal/attachments/')) return jsonResponse({ unlinked: true });
    if (call === 'POST /meetings/m1/multimodal/alignment') { server.data = { ...server.data, alignment: { ...server.data.alignment, state: 'queued', run: { id: 'r2', status: 'queued', error: null, model: null, stats: {} } } }; return jsonResponse({ created: true, ...server.data }); }
    if (call === 'POST /meetings/m1/multimodal/analysis') return jsonResponse({ created: true, ...server.data });
    if (call === 'PUT /meetings/m1/multimodal/windows/0-0/review') return jsonResponse({ window: win({ review_status: body.decision === 'confirmed' ? 'confirmed' : body.decision }) });
    if (call === 'POST /meetings/m1/multimodal/ask') return jsonResponse(options.answer ?? {});
    const act = url.pathname.match(/^\/meeting-multimodal\/items\/(.+)\/(accept|dismiss)$/);
    if (act) {
      const items = server.data.analysis.items.map((i: Obj) => (i.id === act[1] ? { ...i, status: act[2] === 'accept' ? 'accepted' : 'dismissed', record_id: act[2] === 'accept' ? 'r9' : null } : i));
      server.data = { ...server.data, analysis: { ...server.data.analysis, items } };
      return jsonResponse({ item: items.find((i: Obj) => i.id === act[1]), record: act[2] === 'accept' ? { kind: 'task', id: 'r9' } : null });
    }
    return jsonResponse({ detail: 'Not Found' }, 404);
  }));
  return { hub, server };
}

afterEach(() => vi.unstubAllGlobals());

async function openTab(name: string) {
  const user = userEvent.setup();
  renderApp('#/meetings/m1');
  await user.click(await screen.findByRole('button', { name }));
  return user;
}

describe('Attached documents tab', () => {
  it('is absent when the feature is off', async () => {
    setup({ enabled: false });
    renderApp('#/meetings/m1');
    await screen.findByRole('button', { name: 'Summary' });
    expect(screen.queryByRole('button', { name: 'Documents' })).not.toBeInTheDocument();
  });

  it('lists attached documents with their status, attaches one from the library and detaches without deleting', async () => {
    const { server } = setup({ data: overview({ documents: [attached(), attached({ document_id: 'd3', title: 'Still reading', state: 'processing', ready: false, page_count: null })] }) });
    const user = await openTab('Documents');
    const list = await screen.findByRole('list', { name: 'Attached documents list' });
    expect(within(list).getByText('Edge Platform Review')).toBeInTheDocument();
    expect(within(list).getByText('Ready')).toBeInTheDocument();
    expect(within(list).getByText('Reading')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Document from your library'), 'd2');
    await user.click(screen.getByRole('button', { name: 'Attach' }));
    await waitFor(() => expect(server.calls.map((c) => c.call)).toContain('POST /meetings/m1/multimodal/attachments'));
    expect(server.calls.find((c) => c.call === 'POST /meetings/m1/multimodal/attachments')!.body).toEqual({ document_id: 'd2' });
    await user.click(screen.getByRole('button', { name: 'Remove Edge Platform Review from this meeting' }));
    await waitFor(() => expect(server.calls.map((c) => c.call)).toContain('DELETE /meetings/m1/multimodal/attachments/d1'));
    expect(screen.getByText(/does not delete it/)).toBeInTheDocument();
  });

  it('refuses a PowerPoint file with the way forward and uploads nothing', async () => {
    const { server } = setup();
    const user = await openTab('Documents');
    const input = await screen.findByLabelText('Upload a document');
    await user.upload(input, new File(['x'], 'deck.pptx'));
    await user.click(screen.getByRole('button', { name: 'Upload and attach' }));
    expect(await screen.findByText(/Export the presentation as a PDF/)).toBeInTheDocument();
    expect(server.calls.some((c) => c.call.includes('documents') && c.call.startsWith('POST'))).toBe(false);
  });

  it('starts the estimate and the combined analysis, and says what the estimates are', async () => {
    const { server } = setup({ data: overview({ alignment: { state: 'not_run', run: null, transcript_changed: false, documents_changed: false, documents_added: false }, windows: [] }) });
    const user = await openTab('Documents');
    await user.click(await screen.findByRole('button', { name: 'Estimate the pages' }));
    await waitFor(() => expect(server.calls.map((c) => c.call)).toContain('POST /meetings/m1/multimodal/alignment'));
    expect(screen.getByText(/cannot know what\s+was on a screen/)).toBeInTheDocument();
    expect(server.calls.some((c) => c.call.includes('/accept'))).toBe(false);
  });

  it('shows the pages nothing was matched to, with the caveat', async () => {
    setup();
    await openTab('Documents');
    const summary = await screen.findByText(/Pages with no confident discussion matched to them \(1\)/);
    expect(summary).toBeInTheDocument();
    expect(screen.getByText(/does not prove they were not shown/)).toBeInTheDocument();
  });

  it('warns when the transcript or a document changed since the estimate', async () => {
    setup({ data: overview({ alignment: { state: 'succeeded', run: { id: 'r1', status: 'succeeded', error: null, model: 'm', stats: {} }, transcript_changed: true, documents_changed: false, documents_added: false } }) });
    await openTab('Documents');
    expect(await screen.findByText(/changed since the pages were estimated/)).toBeInTheDocument();
  });

  it('shows a failed run with a fixed message and retries it', async () => {
    const { server } = setup({ data: overview({ alignment: { state: 'failed', run: { id: 'r1', status: 'failed', error: 'model_unavailable', model: null, stats: {} }, transcript_changed: false, documents_changed: false, documents_added: false } }) });
    const user = await openTab('Documents');
    expect(await screen.findByText('The local model was not available.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(server.calls.map((c) => c.call)).toContain('POST /meeting-multimodal/runs/r1/retry'));
  });
});

describe('Slide suggestions in the transcript', () => {
  it('shows a likely slide with its title and certainty beside the line, and an unobtrusive note where there is none', async () => {
    setup();
    await openTab('Transcript');
    const card = await screen.findByLabelText('Slide suggestion at 0:00');
    expect(within(card).getByText(/Likely slide 2/)).toBeInTheDocument();
    expect(within(card).getByText(/Edge Architecture/)).toBeInTheDocument();
    expect(within(card).getByText('Certainty: High')).toBeInTheDocument();
    expect(screen.getByText(/No confident slide association/)).toBeInTheDocument();
  });

  it('expands to the reason, an honest caveat and a link that opens the page', async () => {
    setup();
    const user = await openTab('Transcript');
    await user.click(await screen.findByRole('button', { name: 'Details for slide 2 at 0:00' }));
    expect(screen.getByText(/Shares these words with the page/)).toBeInTheDocument();
    expect(screen.getByText(/does not show what was on a screen/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open the page' })).toHaveAttribute('href', '#/documents/d1?page=2');
  });

  it('confirms, chooses an alternative and marks a part as not about a slide', async () => {
    const alt = { document_id: 'd1', document_title: 'Edge Platform Review', page: 4, title: 'Cost Model' };
    const { server } = setup({ data: overview({ windows: [win({ suggestion: suggestion({ certainty: 'medium', alternatives: [alt] }), shown: shown({ certainty: 'medium' }) })] }) });
    const user = await openTab('Transcript');
    await user.click(await screen.findByRole('button', { name: 'Details for slide 2 at 0:00' }));
    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    await user.click(screen.getByRole('button', { name: /Use page 4/ }));
    await user.click(screen.getByRole('button', { name: 'Not about a slide' }));
    await waitFor(() => expect(server.calls.filter((c) => c.call === 'PUT /meetings/m1/multimodal/windows/0-0/review').map((c) => c.body)).toEqual([
      { decision: 'confirmed', document_id: 'd1', page: 2 },
      { decision: 'replaced', document_id: 'd1', page: 4 },
      { decision: 'no_slide' },
    ]));
  });

  it('marks an owner decision, an out-of-date one and a possible disagreement honestly', async () => {
    setup({ data: overview({ windows: [win({
      review_status: 'needs_revalidation', stale: true, owner: { decision: 'confirmed', valid: false, document_id: 'd1', page: 2 }, shown: shown({ authority: 'owner_stale', certainty: null }),
      suggestion: suggestion({ relation: 'contradicts', contradictions: [{ document_id: 'd1', page: 2, slide_quote: 'Latency target is 200 ms', spoken_quote: 'it is actually five hundred' }] }),
    })] }) });
    const user = await openTab('Transcript');
    expect(await screen.findByText('Out of date')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Details for slide 2 at 0:00' }));
    expect(screen.getByText(/Confirm it again to keep it/)).toBeInTheDocument();
    expect(screen.getByText(/The page says: “Latency target is 200 ms”/)).toBeInTheDocument();
    expect(screen.getByText(/It was said: “it is actually five hundred”/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Confirm again' })).toBeInTheDocument();
  });

  it('renders document and model text literally', async () => {
    setup({ data: overview({ windows: [win({ suggestion: suggestion({ slide_title: '<b>Bold</b>', model_note: '<img src=x onerror=alert(1)>' }), shown: shown({ slide_title: '<b>Bold</b>' }) })] }) });
    const user = await openTab('Transcript');
    await user.click(await screen.findByRole('button', { name: /Details for slide 2/ }));
    expect(screen.getByText(/<b>Bold<\/b>/)).toBeInTheDocument();
    expect(document.body.querySelector('b')).toBeNull();
    expect(document.body.querySelector('img[src="x"]')).toBeNull();
  });

  it('shows a continued slide as a thin marker instead of repeating the card', async () => {
    setup({ data: overview({ windows: [win(), win({ window_key: '1-1', segment_ids: [1], start: 20, end: 28 })] }) });
    await openTab('Transcript');
    expect(await screen.findByText('↳ still about page 2')).toBeInTheDocument();
  });
});

describe('Questions and findings', () => {
  const answer = {
    answered: true, abstained: false, message: null, sensitivity: 'work-private', model: 'm', latency_ms: 1200, caveats: ['Which page a part of the discussion was about is an estimate.'], associations: [],
    possible_disagreements: [], parts: [
      { kind: 'document', label: 'What the document says', text: 'The page says latency is 200 ms.', cites: ['D1'], note: null },
      { kind: 'speaker', label: 'What was said', text: 'Someone said it is 500 ms.', cites: ['T1'], note: null },
    ],
    citations: { D1: { id: 'D1', source: 'document', document_id: 'd1', title: 'Edge Platform Review', page: 2, excerpt: 'Latency target' }, T1: { id: 'T1', source: 'transcript', start: 20, speaker: 'Speaker 2', excerpt: 'five hundred' } },
  };

  it('answers with separate labelled parts and citations that open the page and the transcript moment', async () => {
    const { server } = setup({ answer });
    const user = await openTab('Documents');
    await user.type(await screen.findByLabelText('Question'), 'Was the latency challenged?');
    await user.click(screen.getByRole('button', { name: 'Ask' }));
    const box = await screen.findByLabelText('Answer');
    expect(within(box).getByText('What the document says')).toBeInTheDocument();
    expect(within(box).getByText('What was said')).toBeInTheDocument();
    expect(within(box).getByRole('link', { name: '[D1] Edge Platform Review, page 2' })).toHaveAttribute('href', '#/documents/d1?page=2');
    expect(within(box).getByRole('button', { name: '[T1] transcript 0:20, Speaker 2' })).toBeInTheDocument();
    expect(server.calls.find((c) => c.call === 'POST /meetings/m1/multimodal/ask')!.body).toEqual({ question: 'Was the latency challenged?' });
    expect(within(box).getByText(/Written by a model from machine-extracted text/)).toBeInTheDocument();
  });

  it('shows an abstention as it is', async () => {
    setup({ answer: { ...answer, parts: [], citations: {}, answered: false, abstained: true, message: "I couldn't find anything about that in this meeting or its attached documents." } });
    const user = await openTab('Documents');
    await user.type(await screen.findByLabelText('Question'), 'What is the parking policy?');
    await user.click(screen.getByRole('button', { name: 'Ask' }));
    expect(await screen.findByText(/couldn't find anything about that/)).toBeInTheDocument();
  });

  it('lists findings by kind with separate quotes, confirms an action only on request and dismisses another', async () => {
    const { server } = setup({ data: overview({ analysis: { state: 'succeeded', run: { id: 'a1', status: 'succeeded', error: null, model: 'm', stats: {} }, items: [
      finding(), finding({ id: 'f2', kind: 'disagreement', status: 'noted', text: 'The page says 200 ms; the speaker said 500', task_text: null }),
    ] } }) });
    const user = await openTab('Documents');
    const findings = await screen.findByLabelText('Combined findings');
    expect(within(findings).getByText('Actions to review')).toBeInTheDocument();
    expect(within(findings).getByText('Where the pages and the discussion differ')).toBeInTheDocument();
    expect(within(findings).getAllByText(/^Said:/).length).toBeGreaterThan(0);
    expect(within(findings).getAllByText(/^The page says:/).length).toBeGreaterThan(0);
    expect(within(findings).getAllByRole('link', { name: 'page 5' })[0]).toHaveAttribute('href', '#/documents/d1?page=5');
    expect(server.calls.some((c) => c.call.includes('/accept'))).toBe(false); // nothing is confirmed by looking
    await user.click(within(findings).getByRole('button', { name: 'Confirm as task' }));
    await waitFor(() => expect(server.calls.map((c) => c.call)).toContain('POST /meeting-multimodal/items/f1/accept'));
    await user.click(await within(await screen.findByLabelText('Combined findings')).findByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(server.calls.map((c) => c.call)).toContain('POST /meeting-multimodal/items/f2/dismiss'));
  });
});

describe('Low, unchecked, partial and slow results', () => {
  it('shows a Low estimate as one muted line that opens to the usual details, and keeps "none" a valid result', async () => {
    setup({ data: overview({ windows: [
      win({ suggestion: suggestion({ certainty: 'low' }), shown: shown({ certainty: 'low' }) }),
      win({ window_key: '1-1', segment_ids: [1], start: 20, end: 28, suggestion: null, shown: null }),
    ] }) });
    const user = await openTab('Transcript');
    const hint = await screen.findByText(/Possibly page 2/);
    expect(hint).toHaveTextContent('low certainty');
    expect(screen.queryByText('Certainty: Low')).not.toBeInTheDocument(); // no badge, no box
    expect(screen.queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument();
    expect(screen.getByText(/No confident slide association/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Details for slide 2 at 0:00' }));
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeInTheDocument();
    expect(screen.getByText('Certainty: Low')).toBeInTheDocument();
  });

  it('says "not checked" for a part the model could not answer, which is different from no match', async () => {
    setup({ data: overview({ windows: [win({ suggestion: null, shown: null, unchecked: true })] }) });
    await openTab('Transcript');
    expect(await screen.findByText(/Not checked: the model’s answer for this part could not be used/)).toBeInTheDocument();
    expect(screen.queryByText(/No confident slide association/)).not.toBeInTheDocument();
  });

  it('presents incomplete runs as partial results', async () => {
    setup({ data: overview({
      alignment: { state: 'succeeded', run: { id: 'r1', status: 'succeeded', error: null, model: 'm', stats: {}, created_at: null, started_at: null }, partial: { missing: 2, of: 21 }, transcript_changed: false, documents_changed: false, documents_added: false },
      analysis: { state: 'succeeded', run: { id: 'a1', status: 'succeeded', error: null, model: 'm', stats: {}, created_at: null, started_at: null }, partial: { missing: 1, of: 6 }, items: [] },
    }) });
    await openTab('Documents');
    expect(await screen.findByText(/Partial result: 2 of 21 parts of the transcript could not be checked/)).toBeInTheDocument();
    expect(screen.getByText(/Partial result: 1 of 6 parts of the meeting could not be read, so any findings from them are missing/)).toBeInTheDocument();
  });

  it('shows elapsed time while a run works, blocks a second start, and sends one request per click', async () => {
    const created = new Date(Date.now() - 45_000).toISOString();
    const { server } = setup({ data: overview({ analysis: { state: 'processing', run: { id: 'a1', status: 'processing', error: null, model: null, stats: {}, created_at: created, started_at: created }, partial: null, items: [] } }) });
    await openTab('Documents');
    const progress = await screen.findByRole('status', { name: 'Analysing with the documents progress' });
    expect(progress).toHaveTextContent(/working · 4\d s/);
    expect(progress).toHaveTextContent('You can leave this page');
    expect(screen.getByRole('button', { name: 'Analyse with documents' })).toBeDisabled();
    expect(server.calls.filter((c) => c.call === 'POST /meetings/m1/multimodal/analysis')).toHaveLength(0);
  });
});

describe('Connection loss during a run', () => {
  it('says so while the hub is unreachable and keeps what it had', async () => {
    const { server } = setup();
    const user = await openTab('Documents');
    await screen.findByRole('list', { name: 'Attached documents list' });
    const real = globalThis.fetch;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('multimodal')) throw new TypeError('network down');
      return real(input, init);
    }));
    await user.click(screen.getByRole('button', { name: 'Estimate the pages again' }));
    await waitFor(() => expect(screen.getByText(/Can.t reach Reachy right now|network down|Failed to fetch/)).toBeInTheDocument());
    expect(screen.getByRole('list', { name: 'Attached documents list' })).toBeInTheDocument();
    expect(server.calls.length).toBeGreaterThan(0);
  });
});
