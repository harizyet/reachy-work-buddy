import { cleanup, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

const status = { ...SAMPLE_STATUS, default_user_id: 'owner-1', owner_bound: false };
const NOW = '2030-01-01T00:00:00Z';
const doc = (id: string, title: string, extra: Record<string, unknown> = {}) => ({
  id, title, filename: `${id}.pdf`, mime_type: 'application/pdf', size_bytes: 2048, source_hash: 'ab'.repeat(32), sensitivity: 'work-private', project_scope: null, state: 'ready',
  processing_priority: 'background', tier: 'basic', page_count: 5, error_code: null, next_tier: 'standard', created_at: NOW, updated_at: NOW, ...extra,
});

interface Chat { id: string; user_id: string; title: string; created_at: string; updated_at: string; turns: any[]; document: { id: string; title: string; available: boolean } | null }
interface Seen { method: string; path: string; body: any }

/** The chat routes with the hub's attachment behaviour (the attachment belongs to the chat and applies to every message of it), in front of the shared fake hub. */
function hub(opts: { library?: boolean; docs?: ReturnType<typeof doc>[]; chats?: Chat[]; deleted?: Set<string> } = {}) {
  createFakeHub({ status });
  const inner = globalThis.fetch;
  const seen: Seen[] = [];
  const state = { chats: opts.chats ?? [], docs: opts.docs ?? [doc('d1', 'Audit policy'), doc('d2', 'Budget')], deleted: opts.deleted ?? new Set<string>(), n: 0 };
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://hub.test');
    const path = url.pathname;
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    const library = path.startsWith('/document-library');
    const chats = path === '/chats' || path.startsWith('/chats/') || path === '/messages';
    if (!library && !chats) return inner(input, init);
    seen.push({ method, path, body });
    if (path === '/document-library/config') return jsonResponse({ enabled: opts.library ?? true });
    if (path === '/document-library/documents') return jsonResponse(state.docs);
    if (path === '/chats' && method === 'GET') return jsonResponse(state.chats.filter((c) => c.user_id === url.searchParams.get('user_id')).map(({ turns: _t, document: _d, ...r }) => r));
    if (path === '/chats' && method === 'POST') {
      const chat: Chat = { id: `c${++state.n}`, user_id: body.user_id, title: body.title, created_at: NOW, updated_at: NOW, turns: [], document: null };
      state.chats.unshift(chat);
      const { turns: _t, document: _d, ...r } = chat;
      return jsonResponse(r);
    }
    let m = path.match(/^\/chats\/([^/]+)\/document$/);
    if (m && method === 'PUT') {
      const chat = state.chats.find((c) => c.id === m![1]);
      if (!chat) return jsonResponse({ detail: 'Chat not found' }, 404);
      if (body.document_id === null) { chat.document = null; return jsonResponse({ document: null }); }
      const found = state.docs.find((d) => d.id === body.document_id);
      if (!found) return jsonResponse({ detail: 'No such document' }, 404);
      chat.document = { id: found.id, title: found.title, available: true };
      return jsonResponse({ document: { id: found.id, title: found.title, available: true } });
    }
    m = path.match(/^\/chats\/([^/]+)$/);
    if (m) {
      const chat = state.chats.find((c) => c.id === m![1] && c.user_id === url.searchParams.get('user_id'));
      if (!chat) return jsonResponse({ detail: 'Chat not found' }, 404);
      if (method === 'DELETE') { state.chats = state.chats.filter((c) => c !== chat); return jsonResponse({ deleted: true }); }
      return jsonResponse({ ...chat, document: chat.document ? { ...chat.document, available: !state.deleted.has(chat.document.id) } : null });
    }
    if (path === '/messages') {
      const chat = state.chats.find((c) => c.id === body.chat_id)!;
      const attached = chat.document;
      const usable = attached && !state.deleted.has(attached.id);
      const reply = usable ? `From the document: ${body.text}` : attached ? "I can't find the document you attached. It may have been removed." : `Reply to: ${body.text}`;
      const citations = usable ? [{ document_id: attached.id, title: attached.title, page: 4 }, { document_id: attached.id, title: attached.title, page: 1 }] : [];
      chat.turns.push({ id: `t${++state.n}`, text: body.text, reply, status: 'complete', web_search: null, document: attached ? { id: attached.id, title: attached.title } : null, citations });
      return jsonResponse({ web_search: null, context_meeting: null, context_document: usable ? attached.title : null, citations, reply, session_id: 's', conversation_id: 'c', active_channel: 'web', delivery_channel: 'web', privacy: 'work-private' });
    }
    throw new Error(`unexpected ${method} ${path}`);
  }));
  return { seen, state };
}

const box = () => screen.getByRole('textbox', { name: 'Message' });
const send = (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole('button', { name: 'Send' }));
const indicator = () => screen.queryByLabelText('Document attachment');
async function choose(user: ReturnType<typeof userEvent.setup>, title: string) {
  await user.click(screen.getByRole('button', { name: /Attach a document|Replace/ }));
  const dialog = within(await screen.findByRole('dialog', { name: 'Choose a document' }));
  await user.click(await dialog.findByRole('button', { name: `Use: ${title}` }));
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Choose a document' })).toBeNull());
}

afterEach(() => vi.unstubAllGlobals());

describe('Chat document picker', () => {
  it('is not offered when the document library is off', async () => {
    hub({ library: false });
    renderApp('#/chat');
    await screen.findByText(/No session yet/);
    expect(screen.queryByRole('button', { name: 'Attach a document' })).toBeNull();
  });

  it('lists documents, offers only the ones that are ready, and starts with nothing attached', async () => {
    hub({ docs: [doc('d1', 'Audit policy'), doc('d2', 'Still reading', { state: 'processing' }), doc('d3', 'Broken', { state: 'failed' })] });
    renderApp('#/chat');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Attach a document' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Choose a document' }));
    expect(await dialog.findByRole('button', { name: 'Use: Audit policy' })).toBeEnabled();
    expect(dialog.getByRole('button', { name: 'Use: Still reading' })).toBeDisabled();
    expect(dialog.getByRole('button', { name: 'Use: Broken' })).toBeDisabled();
    expect(dialog.getByText(/still being read/)).toBeInTheDocument();
    expect(dialog.getByText(/could not be read/)).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('button', { name: 'Attach a document' })).toBeInTheDocument();
    expect(screen.queryByText(/Answering from/)).toBeNull();
  });

  it('keeps the attachment for follow-up messages and shows the pages used, saving it with the new chat before the first answer', async () => {
    const h = hub();
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText(/No session yet/);
    await choose(user, 'Audit policy');
    expect(screen.getByText(/Answering from:/).parentElement).toHaveTextContent('Audit policy');
    expect(h.seen.some((s) => s.method === 'PUT')).toBe(false); // no chat yet: nothing saved
    await user.type(box(), 'How long is retention?');
    await send(user);
    expect(await screen.findByText('From the document: How long is retention?')).toBeInTheDocument();
    expect(screen.getByText(/From pages 1, 4 of “Audit policy”/)).toBeInTheDocument();
    const order = h.seen.filter((s) => (s.method === 'POST' && ['/chats', '/messages'].includes(s.path)) || s.method === 'PUT').map((s) => `${s.method} ${s.path.replace(/c\d+/, 'cN')}`);
    expect(order).toEqual(['POST /chats', 'PUT /chats/cN/document', 'POST /messages']);
    expect(h.seen.find((s) => s.path === '/messages')!.body).not.toHaveProperty('context_document_id'); // the hub applies the chat's own attachment
    // a follow-up is answered from it again without choosing anything
    await user.type(box(), 'And the second page?');
    await send(user);
    expect(await screen.findByText('From the document: And the second page?')).toBeInTheDocument();
    expect(h.seen.filter((s) => s.method === 'PUT')).toHaveLength(1);
    expect(screen.getByLabelText('Document attachment')).toHaveTextContent('Audit policy');
  });

  it('replaces and removes the attachment, and an ordinary message after removal is ordinary chat', async () => {
    const h = hub();
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText(/No session yet/);
    await user.type(box(), 'hello');
    await send(user);
    await screen.findByText('Reply to: hello');
    await choose(user, 'Audit policy');
    await waitFor(() => expect(indicator()).toHaveTextContent('Audit policy'));
    expect(h.seen.filter((s) => s.method === 'PUT').map((s) => s.body.document_id)).toEqual(['d1']); // an existing chat saves it at once
    await choose(user, 'Budget');
    await waitFor(() => expect(indicator()).toHaveTextContent('Budget'));
    expect(h.seen.filter((s) => s.method === 'PUT').map((s) => s.body.document_id)).toEqual(['d1', 'd2']);
    await user.type(box(), 'budget?');
    await send(user);
    expect(await screen.findByText('From the document: budget?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Stop answering from this document' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Attach a document' })).toBeInTheDocument());
    expect(h.seen.filter((s) => s.method === 'PUT').at(-1)!.body.document_id).toBeNull();
    await user.type(box(), 'two plus two');
    await send(user);
    expect(await screen.findByText('Reply to: two plus two')).toBeInTheDocument();
    expect(screen.getAllByText(/From pages/)).toHaveLength(1); // only the one answered from the document
  });

  it('survives a page refresh within the conversation and shows the saved pages in the transcript', async () => {
    const h = hub();
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText(/No session yet/);
    await choose(user, 'Audit policy');
    await user.type(box(), 'retention?');
    await send(user);
    await screen.findByText('From the document: retention?');
    cleanup(); // a refresh: everything in the browser is gone, the hub keeps the chat
    renderApp('#/chat');
    await screen.findByText('From the document: retention?');
    expect(screen.getByLabelText('Document attachment')).toHaveTextContent('Audit policy');
    expect(screen.getByText(/From pages 1, 4 of “Audit policy”/)).toBeInTheDocument();
    await user.type(box(), 'after the refresh');
    await send(user);
    expect(await screen.findByText('From the document: after the refresh')).toBeInTheDocument();
    expect(h.state.chats).toHaveLength(1);
  });

  it('keeps each conversation\'s attachment separate when switching, and a new conversation has none', async () => {
    const chats: Chat[] = [
      { id: 'a', user_id: 'owner-1', title: 'About the policy', created_at: NOW, updated_at: '2030-01-03T00:00:00Z', turns: [], document: { id: 'd1', title: 'Audit policy', available: true } },
      { id: 'b', user_id: 'owner-1', title: 'About lunch', created_at: NOW, updated_at: '2030-01-02T00:00:00Z', turns: [], document: null },
      { id: 'c', user_id: 'owner-1', title: 'About the budget', created_at: NOW, updated_at: '2030-01-01T00:00:00Z', turns: [], document: { id: 'd2', title: 'Budget', available: true } },
    ];
    hub({ chats });
    renderApp('#/chat');
    const user = userEvent.setup();
    await waitFor(() => expect(indicator()).toHaveTextContent('Audit policy')); // the most recent chat opens with its own attachment
    await user.click(await screen.findByRole('button', { name: /^About lunch/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Attach a document' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /^About the budget/ }));
    await waitFor(() => expect(indicator()).toHaveTextContent('Budget'));
    await user.click(screen.getByRole('button', { name: /^About the policy/ }));
    await waitFor(() => expect(indicator()).toHaveTextContent('Audit policy'));
    await user.click(screen.getByRole('button', { name: /New chat record/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Attach a document' })).toBeInTheDocument());
    // something chosen in a new, unsaved chat is dropped if the owner opens another conversation instead
    await choose(user, 'Budget');
    await user.click(screen.getByRole('button', { name: /^About lunch/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Attach a document' })).toBeInTheDocument());
    expect(screen.queryByText(/Answering from/)).toBeNull();
  });

  it('shows a deleted document as unavailable, relays the fixed reply, and lets the owner remove it', async () => {
    const chats: Chat[] = [{ id: 'a', user_id: 'owner-1', title: 'About the policy', created_at: NOW, updated_at: NOW, turns: [], document: { id: 'd1', title: 'Audit policy', available: true } }];
    const h = hub({ chats, deleted: new Set(['d1']) });
    renderApp('#/chat');
    const user = userEvent.setup();
    expect(await screen.findByRole('alert')).toHaveTextContent('no longer available');
    await user.type(box(), 'what did it say?');
    await send(user);
    expect(await screen.findByText(/I can't find the document you attached/)).toBeInTheDocument();
    expect(screen.queryByText(/From pages/)).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Stop answering from this document' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Attach a document' })).toBeInTheDocument());
    expect(h.seen.some((s) => s.method === 'PUT' && s.body.document_id === null)).toBe(true);
  });

  it('says so when a document cannot be attached and leaves the chat as it was', async () => {
    const chats: Chat[] = [{ id: 'a', user_id: 'owner-1', title: 'A chat', created_at: NOW, updated_at: NOW, turns: [], document: null }];
    const h = hub({ chats });
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText(/No session yet|User:/);
    h.state.docs = []; // the document vanished between listing and choosing
    h.state.docs.push(doc('gone', 'Vanishing'));
    await user.click(await screen.findByRole('button', { name: 'Attach a document' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Choose a document' }));
    h.state.docs = [];
    await user.click(await dialog.findByRole('button', { name: 'Use: Vanishing' }));
    expect(await screen.findByText(/Could not attach that document: No such document/)).toBeInTheDocument();
    expect(screen.queryByText(/Answering from/)).toBeNull();
  });

  it('renders the document title and pages as literal text', async () => {
    hub({ docs: [doc('d1', '<img src=x onerror=boom()> Policy')] });
    const { container } = renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText(/No session yet/);
    await choose(user, '<img src=x onerror=boom()> Policy');
    expect(container.querySelector('img[src="x"]')).toBeNull();
    expect(screen.getByLabelText('Document attachment')).toHaveTextContent('<img src=x onerror=boom()> Policy');
  });
});
