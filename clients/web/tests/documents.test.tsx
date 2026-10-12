import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse } from './fakeHub';
import { navLink, renderApp, SAMPLE_STATUS } from './helpers';

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

function hubWith(opts: { enabled?: boolean; docs?: ReturnType<typeof doc>[]; summaries?: ReturnType<typeof summary>[]; noImage?: boolean; exportFails?: boolean } = {}) {
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
      const inspect = rest?.match(/^\/inspect\/pages\/(\d+)(\/blocks\/(\d+))?(\/image)?$/);
      if (inspect) {
        const pageNo = Number(inspect[1]);
        if (inspect[4]) return opts.noImage ? jsonResponse({ detail: 'There is no picture of that' }, 404) : new Response(`png-${pageNo}-${inspect[3] ?? 'page'}`, { status: 200, headers: { 'Content-Type': 'image/png' } });
        return jsonResponse({
          document_id: id, title: 'Policy', source_hash: 'ab'.repeat(32), evidence_type: 'derived_extraction', state: 'ready', tier: 'basic', next_tier: 'standard', source_type: opts.noImage ? 'docx' : 'pdf', page: pageNo, page_count: 2,
          page_image: !opts.noImage, width_pt: 595, height_pt: 842,
          blocks: [{ block: 1, type: 'paragraph_title', bbox: opts.noImage ? null : [0.1, 0.05, 0.6, 0.1] }, { block: 2, type: 'table', bbox: opts.noImage ? null : [0.1, 0.2, 0.7, 0.4] }],
          markdown: `<!-- page ${pageNo} of 2 -->\n\n## <img src=x onerror=boom()> Heading ${pageNo}\n\n| a | b |`,
          html: `<style>.docvortex-text{color:#123}</style><article><p class="docvortex-text">Extracted text ${pageNo}</p><script>boom()</script></article>`,
        });
      }
      if (rest?.startsWith('/export')) {
        if (opts.exportFails) return jsonResponse({ detail: 'The document is not processed yet' }, 409);
        return new Response(`export:${url.searchParams.get('format')}`, { status: 200, headers: { 'Content-Type': 'text/plain' } });
      }
      if (rest === '/original') return new Response('%PDF-original', { status: 200, headers: { 'Content-Type': 'application/pdf' } });
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

const saved: { name: string; text: string }[] = [];
vi.mock('../src/utils/download', () => ({
  saveBlob: (blob: Blob, name: string) => { void blob.text().then((text) => saved.push({ name, text })); },
}));

beforeEach(() => {
  saved.length = 0;
  URL.createObjectURL = vi.fn(() => 'blob:test-image');
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

describe('Documents', () => {
  it('says so when the library is off, and has a nav link', async () => {
    hubWith({ enabled: false });
    renderApp('#/documents');
    await screen.findByText(/document library is not turned on/);
    expect(await navLink(userEvent.setup(), 'Documents')).toBeInTheDocument();
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
    await user.click(screen.getByRole('button', { name: 'Write executive summary' }));
    await waitFor(() => expect(hub.seen.some((s) => s.path.endsWith('/summaries') && s.method === 'POST' && (s.body as any).style === 'executive')).toBe(true));
    await user.click(screen.getByRole('button', { name: 'Technical summary' })); // the one that exists is shown again, without asking for it a second time
    await screen.findByText('It sets seven-day retention [page 1].');
    await user.click(screen.getByRole('button', { name: 'Make it again' }));
    await waitFor(() => expect(hub.seen.some((s) => (s.body as any)?.force === true && (s.body as any).style === 'technical')).toBe(true));
  });

  it('the style buttons choose which summary is shown; one that exists is shown at once without a request, one that does not is written', async () => {
    const hub = hubWith({ docs: [doc('d1', 'Policy')], summaries: [
      summary('s1', 'ordinary', { text: 'Plain summary text.' }), summary('s2', 'executive', { text: 'Executive summary text.' })] });
    renderApp('#/documents/d1');
    const user = userEvent.setup();
    await screen.findByText('Plain summary text.');
    const group = screen.getByRole('group', { name: 'Summary style' });
    expect(within(group).getByRole('button', { name: 'Summary' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByText('Executive summary text.')).not.toBeInTheDocument(); // only the chosen style is on screen
    await user.click(within(group).getByRole('button', { name: 'Executive summary' }));
    expect(await screen.findByText('Executive summary text.')).toBeInTheDocument();
    expect(screen.queryByText('Plain summary text.')).not.toBeInTheDocument();
    expect(within(group).getByRole('button', { name: 'Executive summary' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(within(group).getByRole('button', { name: 'Summary' }));
    expect(await screen.findByText('Plain summary text.')).toBeInTheDocument();
    expect(hub.seen.filter((s) => s.path.endsWith('/summaries') && s.method === 'POST')).toHaveLength(0); // showing what exists asks for nothing
    await user.click(within(group).getByRole('button', { name: 'Write technical summary' }));
    await waitFor(() => expect(hub.seen.filter((s) => s.path.endsWith('/summaries') && s.method === 'POST')).toHaveLength(1));
    expect(within(group).getByRole('button', { name: 'Technical summary…' })).toBeDisabled(); // writing: the button says so
    expect(screen.queryByText('Plain summary text.')).not.toBeInTheDocument();
    expect(await screen.findByText('Writing')).toBeInTheDocument();
  });

  it('with no summary yet it says so and writes the one chosen', async () => {
    const hub = hubWith({ docs: [doc('d1', 'Policy')] });
    renderApp('#/documents/d1');
    const user = userEvent.setup();
    expect(await screen.findByText('No summary yet. Choose a style to have Reachy write one.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Write summary' }));
    await waitFor(() => expect(hub.seen.some((s) => s.path.endsWith('/summaries') && s.method === 'POST' && (s.body as any).style === 'ordinary')).toBe(true));
    expect(await screen.findByText('Writing')).toBeInTheDocument();
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

  describe('extraction inspector', () => {
    async function openInspector(opts: Parameters<typeof hubWith>[0] = { docs: [doc('d1', 'Policy')] }) {
      const hub = hubWith(opts);
      const view = renderApp('#/documents/d1');
      const user = userEvent.setup();
      await user.click(await screen.findByRole('button', { name: 'Inspect extraction' }));
      await screen.findByRole('region', { name: 'Extraction inspector' });
      return { hub, user, ...view };
    }

    it('puts the original page beside what MinerU extracted, with tier, page count and block overlay', async () => {
      const { hub } = await openInspector();
      await screen.findByRole('img', { name: /Page 1 of Policy, as in the original/ });
      expect(screen.getByText('Read at Basic')).toBeInTheDocument();
      expect(screen.getByRole('group', { name: 'Page navigation' })).toHaveTextContent('of 2');
      expect(screen.getByRole('button', { name: 'Block 1, paragraph_title' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Block 2, table' })).toBeInTheDocument();
      const imageRequest = hub.seen.find((s) => s.path.endsWith('/inspect/pages/1/image'))!;
      expect(imageRequest.method).toBe('GET');
      expect(imageRequest.csrf).toBe('1');
    });

    it('shows the extraction only in a locked frame, and markdown as literal text', async () => {
      const { user, container } = await openInspector();
      const frame = await screen.findByTitle(/Extracted page 1, rendered by MinerU/);
      expect(frame).toHaveAttribute('sandbox', '');
      expect(frame.getAttribute('srcdoc')).toContain("default-src 'none'");
      for (const directive of ["img-src 'none'", "connect-src 'none'", "form-action 'none'", "base-uri 'none'", "frame-src 'none'", "object-src 'none'"]) expect(frame.getAttribute('srcdoc')).toContain(directive);
      expect(frame.getAttribute('srcdoc')).toContain('no-referrer');
      expect(frame.getAttribute('sandbox')).toBe(''); // not even allow-same-origin, allow-scripts, allow-forms, allow-popups or allow-top-navigation
      expect(frame.getAttribute('srcdoc')).toContain('Extracted text 1');
      expect(document.querySelector('.docvortex-text, script')).toBeNull(); // nothing from the extraction was put into the page itself
      await user.click(screen.getByRole('tab', { name: 'Markdown' }));
      await screen.findByText(/Heading 1/);
      expect(container.querySelector('img[src="x"]')).toBeNull();
      await user.click(screen.getByRole('tab', { name: /Blocks \(2\)/ }));
      expect(screen.getByRole('row', { name: /1 paragraph_title/ })).toBeInTheDocument();
    });

    it('moves page by page and keeps the original and the extraction on the same page', async () => {
      const { hub, user } = await openInspector();
      await screen.findByRole('img', { name: /Page 1 of Policy/ });
      expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled();
      await user.click(screen.getByRole('button', { name: 'Next page' }));
      await screen.findByRole('img', { name: /Page 2 of Policy/ });
      await screen.findByTitle(/Extracted page 2, rendered by MinerU/);
      expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled();
      expect(hub.seen.some((s) => s.path.endsWith('/inspect/pages/2/image'))).toBe(true);
      const box = screen.getByLabelText('Page number');
      await user.clear(box); // an empty box means page 1
      await screen.findByRole('img', { name: /Page 1 of Policy/ });
      expect(box).toHaveValue(1);
    });

    it('cuts out a selected block with MinerU and lets it be dismissed', async () => {
      const { hub, user } = await openInspector();
      await user.click(await screen.findByRole('button', { name: 'Block 2, table' }));
      await screen.findByRole('img', { name: /Block 2 \(table\) cut from the page/ });
      expect(hub.seen.some((s) => s.path.endsWith('/inspect/pages/1/blocks/2/image'))).toBe(true);
      await user.click(screen.getByRole('button', { name: 'Block 2, table' }));
      await waitFor(() => expect(screen.queryByLabelText('Selected block')).toBeNull());
      await user.click(screen.getByLabelText('Show blocks on the page'));
      expect(screen.queryByRole('button', { name: 'Block 1, paragraph_title' })).toBeNull();
    });

    it('offers the existing Improve reading from inside the inspector', async () => {
      const { hub, user } = await openInspector();
      const inside = within(screen.getByRole('region', { name: 'Extraction inspector' }));
      await user.click(inside.getByRole('button', { name: /Improve reading \(Standard\)/ }));
      await waitFor(() => expect(hub.seen.some((s) => s.path.endsWith('/reprocess') && (s.body as any).tier === 'standard')).toBe(true));
    });

    it('downloads Markdown, HTML, both structured results and the original, named from the title', async () => {
      const { user } = await openInspector();
      const group = within(screen.getByRole('group', { name: 'Downloads' }));
      for (const label of ['Markdown', 'HTML', 'Content list (JSON)', 'Structured result (JSON)', 'Original file']) await user.click(group.getByRole('button', { name: label }));
      await waitFor(() => expect(saved).toHaveLength(5));
      expect(saved.map((s) => s.name).sort()).toEqual(['Policy-basic-content_list.json', 'Policy-basic-html.html', 'Policy-basic-markdown.md', 'Policy-basic-middle_json.json', 'Policy-basic-original.pdf']);
      expect(saved.find((s) => s.name.endsWith('markdown.md'))!.text).toBe('export:markdown');
      expect(saved.find((s) => s.name.endsWith('original.pdf'))!.text).toBe('%PDF-original');
    });

    it('says plainly when there is no page picture, and when a download fails', async () => {
      const { user } = await openInspector({ docs: [doc('d1', 'Memo', { mime_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })], noImage: true, exportFails: true });
      await screen.findByText(/no page picture for this kind of file/);
      expect(screen.queryByLabelText('Show blocks on the page')).toBeNull();
      await user.click(within(screen.getByRole('group', { name: 'Downloads' })).getByRole('button', { name: 'Markdown' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('not processed yet');
    });

    it('is not offered until the document is ready', async () => {
      hubWith({ docs: [doc('d1', 'Policy', { state: 'processing' })] });
      renderApp('#/documents/d1');
      await screen.findByText(/still reading this document/);
      expect(screen.queryByRole('button', { name: 'Inspect extraction' })).toBeNull();
    });
  });
});

