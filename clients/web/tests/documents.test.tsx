import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

const NOW = new Date().toISOString();
const doc = (id: string, title: string, extra: Record<string, unknown> = {}) => ({
  id, title, filename: `${id}.pdf`, mime_type: 'application/pdf', size_bytes: 2048, source_hash: 'ab'.repeat(32), sensitivity: 'work-private', project_scope: null, state: 'ready',
  processing_priority: 'background', tier: 'basic', page_count: 2, error_code: null, next_tier: 'standard', created_at: NOW, updated_at: NOW, ...extra,
});
const summary = (id: string, style: string, extra: Record<string, unknown> = {}) => ({
  id, document_id: 'd1', style, status: 'ready', text: 'It sets seven-day retention [page 1].', sections: [], pages_covered: '1-2', page_count: 2, truncated: false, source_hash: 'ab'.repeat(32),
  tier: 'basic', sensitivity: 'work-private', model: 'reachy-local', stale: false, current: true, error_code: null, created_at: NOW, ...extra,
});

interface Seen { method: string; path: string; body: unknown; csrf: string | null; form: Record<string, string | File> | null }

function hubWith(opts: { enabled?: boolean; docs?: ReturnType<typeof doc>[]; summaries?: ReturnType<typeof summary>[] } = {}) {
  createFakeHub({ status: SAMPLE_STATUS });
  const inner = globalThis.fetch;
  const seen: Seen[] = [];
  let docs = opts.docs ?? [];
  let summaries = opts.summaries ?? [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://hub.test');
    const isLibrary = url.pathname.startsWith('/document-library');
    const isAsk = url.pathname === '/messages';
    if (!isLibrary && !isAsk) return inner(input, init);
    const method = init?.method ?? 'GET';
    const headers = (init?.headers ?? {}) as Record<string, string>;
    const form = init?.body instanceof FormData ? Object.fromEntries(init.body.entries()) : null;
    const body = init?.body && !form ? JSON.parse(String(init.body)) : undefined;
    seen.push({ method, path: url.pathname, body, csrf: headers['X-Reachy-CSRF'] ?? null, form });
    if (isAsk) return jsonResponse({ reply: 'Seven days [page 1].', context_document: 'Policy', citations: [{ document_id: 'd1', title: 'Policy', page: 1, locator: null }], session_id: 's', conversation_id: 'c', active_channel: 'web', delivery_channel: 'web', privacy: 'work-private' });
    if (url.pathname === '/document-library/config') return jsonResponse({ enabled: opts.enabled ?? true });
    if (url.pathname === '/document-library/documents' && method === 'GET') return jsonResponse(docs);
    if (url.pathname === '/document-library/documents' && method === 'POST') {
      const created = doc('new1', String(form?.title || 'Uploaded'), { state: 'queued', tier: 'basic', page_count: null });
      docs = [created, ...docs];
      return jsonResponse(created, 201);
    }
    const one = url.pathname.match(/^\/document-library\/documents\/([^/]+)(\/.*)?$/);
    if (one) {
      const [, id, rest] = one;
      if (!rest && method === 'DELETE') { docs = docs.filter((d) => d.id !== id); return new Response(null, { status: 204 }); }
      if (!rest && method === 'PATCH') { docs = docs.map((d) => (d.id === id ? { ...d, ...body } : d)); return jsonResponse(docs.find((d) => d.id === id)); }
      if (rest === '/reprocess') { docs = docs.map((d) => (d.id === id ? { ...d, state: 'queued', tier: body.tier ?? d.tier } : d)); return jsonResponse(docs.find((d) => d.id === id)); }
      if (rest === '/search') return jsonResponse({ document_id: id, title: 'Policy', hits: [{ snippet: '<b>The retention requirement</b> is 7 days.', page: 1, locator: 'doc:x/tier:basic/page:1' }], complete: true });
      if (rest === '/summaries' && method === 'GET') return jsonResponse(summaries);
      if (rest === '/summaries' && method === 'POST') {
        const made = summary('s-new', body.style, { status: 'running', text: '' });
        summaries = [made, ...summaries.filter((s) => !(body.force && s.style === body.style))];
        return jsonResponse(made, 202);
      }
    }
    throw new Error(`unexpected ${method} ${url.pathname}`);
  }));
  return { seen };
}

afterEach(() => vi.unstubAllGlobals());

describe('Documents', () => {
  it('says so when the library is off, and has a nav link', async () => {
    hubWith({ enabled: false });
    renderApp('#/documents');
    await screen.findByText(/document library is not turned on/);
    expect(screen.getByRole('link', { name: 'Documents' })).toBeInTheDocument();
  });

  it('lists documents as literal text with their state and class', async () => {
    hubWith({ docs: [doc('d1', '<img src=x onerror=boom()> Policy'), doc('d2', 'Scan', { state: 'processing', sensitivity: 'sensitive', project_scope: 'Alpha' })] });
    const { container } = renderApp('#/documents');
    await screen.findByText(/Policy/);
    expect(container.querySelector('img')).toBeNull();
    const list = screen.getByRole('list', { name: 'Documents' });
    expect(within(list).getByText('Ready')).toBeInTheDocument();
    expect(within(list).getByText('Reading')).toBeInTheDocument();
    expect(within(list).getByText(/Sensitive · Alpha/)).toBeInTheDocument();
  });

  it('uploads a file with its class and priority, sends the CSRF header, and opens the new document', async () => {
    const hub = hubWith();
    renderApp('#/documents');
    const user = userEvent.setup();
    const file = new File(['%PDF-1.4'], 'tender.pdf', { type: 'application/pdf' });
    await user.upload(await screen.findByLabelText('File'), file);
    await user.type(screen.getByLabelText(/Title/), 'The Tender');
    await user.selectOptions(screen.getByLabelText('Class'), 'sensitive');
    await user.selectOptions(screen.getByLabelText('Reading priority'), 'interactive');
    await user.click(screen.getByRole('button', { name: 'Upload' }));
    await screen.findByRole('article', { name: /The Tender/ });
    const post = hub.seen.find((s) => s.method === 'POST' && s.path === '/document-library/documents')!;
    expect(post.csrf).toBe('1');
    expect(post.form).toMatchObject({ title: 'The Tender', sensitivity: 'sensitive', processing_priority: 'interactive' });
    expect((post.form!.file as File).name).toBe('tender.pdf');
  });

  it('shows no tools until a document is ready, and says why', async () => {
    hubWith({ docs: [doc('d1', 'Policy', { state: 'processing', page_count: null })] });
    renderApp('#/documents/d1');
    await screen.findByText(/still reading this document/);
    expect(screen.queryByRole('button', { name: 'Ask' })).toBeNull();
  });

  it('asks a question about the attached document and shows the pages the answer came from', async () => {
    const hub = hubWith({ docs: [doc('d1', 'Policy')] });
    renderApp('#/documents/d1');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Your question'), 'How long is retention?');
    await user.click(screen.getByRole('button', { name: 'Ask' }));
    await screen.findByText('Seven days [page 1].');
    expect(screen.getByText(/From pages: 1 of/)).toBeInTheDocument();
    const sent = hub.seen.find((s) => s.path === '/messages')!;
    expect(sent.body).toMatchObject({ channel: 'web', input_modality: 'text', text: 'How long is retention?', context_document_id: 'd1' });
    expect(sent.body).not.toHaveProperty('access_ceiling');
  });

  it('searches inside the document and shows hits as text with their page', async () => {
    hubWith({ docs: [doc('d1', 'Policy')] });
    const { container } = renderApp('#/documents/d1');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Search words'), 'retention');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await screen.findByText(/The retention requirement/);
    expect(screen.getByText('Page 1')).toBeInTheDocument();
    expect(container.querySelector('b')).toBeNull();
  });

  it('starts summaries, shows them with provenance, and offers a new one when out of date', async () => {
    const hub = hubWith({ docs: [doc('d1', 'Policy')], summaries: [summary('s1', 'technical', { stale: true, current: false })] });
    renderApp('#/documents/d1');
    const user = userEvent.setup();
    await screen.findByText('It sets seven-day retention [page 1].');
    expect(screen.getByText('Out of date')).toBeInTheDocument();
    expect(screen.getByText(/Read at basic · pages 1-2 of 2 · reachy-local/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Executive summary' }));
    await waitFor(() => expect(hub.seen.some((s) => s.path.endsWith('/summaries') && s.method === 'POST' && (s.body as any).style === 'executive')).toBe(true));
    await user.click(screen.getByRole('button', { name: 'Make it again' }));
    await waitFor(() => expect(hub.seen.some((s) => (s.body as any)?.force === true && (s.body as any).style === 'technical')).toBe(true));
  });

  it('explains a failed summary instead of showing an empty one', async () => {
    hubWith({ docs: [doc('d1', 'Scan')], summaries: [summary('s1', 'ordinary', { status: 'failed', text: '', error_code: 'sparse_text' })] });
    renderApp('#/documents/d1');
    await screen.findByText(/Very little text could be read/);
    expect(screen.getByRole('button', { name: 'Make it again' })).toBeInTheDocument();
  });

  it('reads again, improves the reading to the next level, and renames', async () => {
    const hub = hubWith({ docs: [doc('d1', 'Policy')] });
    renderApp('#/documents/d1');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Improve reading \(Standard\)/ }));
    await waitFor(() => expect(hub.seen.some((s) => s.path.endsWith('/reprocess') && (s.body as any).tier === 'standard')).toBe(true));
    const title = screen.getByLabelText('Title');
    await user.clear(title);
    await user.type(title, 'Renamed');
    await user.click(screen.getByRole('button', { name: 'Rename' }));
    await waitFor(() => expect(hub.seen.some((s) => s.method === 'PATCH' && (s.body as any).title === 'Renamed')).toBe(true));
  });

  it('asks before deleting, then removes the document and returns to the list', async () => {
    const hub = hubWith({ docs: [doc('d1', 'Policy')] });
    renderApp('#/documents/d1');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Delete…' }));
    expect(hub.seen.some((s) => s.method === 'DELETE')).toBe(false);
    await user.click(screen.getByRole('button', { name: 'Keep it' }));
    await user.click(screen.getByRole('button', { name: 'Delete…' }));
    await user.click(screen.getByRole('button', { name: 'Delete it' }));
    await screen.findByText('No documents yet.');
    expect(hub.seen.filter((s) => s.method === 'DELETE')).toHaveLength(1);
  });
});
