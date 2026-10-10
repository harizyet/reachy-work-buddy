import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseCandidates } from '../src/api/memoryCandidates';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

const NOW = new Date().toISOString();
const LATER = new Date(Date.now() + 14 * 86_400_000).toISOString();
const cand = (id: string, text: string, extra: Record<string, unknown> = {}) => ({
  id, text, status: 'pending', rule_id: 'preference.prefer', rule_version: 1, conversation_id: 'conv-1', session_id: 's', turn_index: 1, channel: 'web', proposed_type: 'profile',
  proposed_scope: null, sensitivity: 'work-private', memory_id: null, edited: false, created_at: NOW, expires_at: LATER, accepting_at: null, decided_at: null, ...extra,
});

interface Seen { method: string; path: string; body: unknown; csrf: string | null }

/** The existing fake hub for the shell and sign-in, with the memory-suggestion routes in front of it. */
function hubWith(initial: ReturnType<typeof cand>[], capture = true) {
  createFakeHub({ status: SAMPLE_STATUS });
  const inner = globalThis.fetch;
  const seen: Seen[] = [];
  let queue = [...initial];
  let failures: (() => Response)[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://hub.test');
    if (!url.pathname.startsWith('/memory-candidates')) return inner(input, init);
    const method = init?.method ?? 'GET';
    const headers = (init?.headers ?? {}) as Record<string, string>;
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    seen.push({ method, path: url.pathname, body, csrf: headers['X-Reachy-CSRF'] ?? null });
    const failure = failures.shift();
    if (failure) return failure();
    if (method === 'GET') return jsonResponse({ candidates: queue, capture_enabled: capture });
    const accept = url.pathname.match(/^\/memory-candidates\/([^/]+)\/accept$/);
    const reject = url.pathname.match(/^\/memory-candidates\/([^/]+)\/reject$/);
    if (accept) {
      const c = queue.find((x) => x.id === accept[1]);
      if (!c) return jsonResponse({ detail: 'No such suggestion' }, 404);
      queue = queue.filter((x) => x !== c);
      return jsonResponse({ candidate: { ...c, status: body && Object.keys(body).length ? 'edited-accepted' : 'accepted', text: null },
        memory: { id: 'm1', content: body?.text ?? c.text, type: body?.type ?? c.proposed_type, sensitivity: body?.sensitivity ?? c.sensitivity, expires_at: null } });
    }
    if (reject) { queue = queue.filter((x) => x.id !== reject[1]); return jsonResponse({ candidate: { status: body.suppress ? 'suppressed' : 'rejected', text: null } }); }
    if (url.pathname === '/memory-candidates/forget-conversation') {
      const before = queue.length;
      queue = queue.filter((x) => x.conversation_id !== body.conversation_id);
      return jsonResponse({ deleted: before - queue.length });
    }
    throw new Error(`unexpected ${method} ${url.pathname}`);
  }));
  return { seen, failWith: (make: () => Response, times = 1) => { failures = Array.from({ length: times }, () => make); } };
}

afterEach(() => vi.unstubAllGlobals());

describe('Memory suggestions', () => {
  it('lists suggestions as literal text, with provenance, and says nothing is saved until accepted', async () => {
    hubWith([cand('c1', '<img src=x onerror=boom()> I prefer tea.')]);
    const { container } = renderApp('#/memory');
    await screen.findByText(/I prefer tea\./);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText(/Nothing is saved until you accept it here/)).toBeInTheDocument();
    expect(screen.getByText(/from your web chat/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Memory' })).toBeInTheDocument();
  });

  it('accepts as it is, sending an empty body, and confirms what was saved', async () => {
    const hub = hubWith([cand('c1', 'I prefer written summaries.')]);
    renderApp('#/memory');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Save to memory: I prefer written summaries/ }));
    await screen.findByText('Saved to memory: I prefer written summaries.');
    const post = hub.seen.find((s) => s.method === 'POST')!;
    expect(post.path).toBe('/memory-candidates/c1/accept');
    expect(post.body).toEqual({});
    expect(post.csrf).toBe('1');
    expect(await screen.findByText('No suggestions are waiting.')).toBeInTheDocument();
  });

  it('edits then accepts, sending only what changed, and needs an acknowledgement to lower the privacy level', async () => {
    const hub = hubWith([cand('c1', 'I prefer written summaries.')]);
    renderApp('#/memory');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Edit: I prefer written summaries/ }));
    const box = screen.getByLabelText('Memory');
    await user.clear(box);
    await user.type(box, 'I prefer short written summaries.');
    await user.selectOptions(screen.getByLabelText(/Sensitivity/), 'public');
    const save = screen.getByRole('button', { name: 'Save edited memory' });
    expect(save).toBeDisabled();
    await user.click(screen.getByLabelText(/lowers the privacy level/));
    expect(save).toBeEnabled();
    await user.selectOptions(screen.getByLabelText(/Keep for/), '90');
    await user.click(save);
    await screen.findByText(/Saved to memory: I prefer short written summaries\./);
    expect(hub.seen.find((s) => s.method === 'POST')!.body).toEqual({ text: 'I prefer short written summaries.', sensitivity: 'public', expires_in_days: 90, acknowledge_lower: true });
  });

  it('refuses empty or over-long edits before sending anything', async () => {
    const hub = hubWith([cand('c1', 'I prefer tea.')]);
    renderApp('#/memory');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Edit: I prefer tea/ }));
    await user.clear(screen.getByLabelText('Memory'));
    expect(screen.getByRole('button', { name: 'Save edited memory' })).toBeDisabled();
    expect(hub.seen.filter((s) => s.method === 'POST')).toHaveLength(0);
  });

  it('dismisses, suppresses, and forgets a whole conversation', async () => {
    const hub = hubWith([cand('c1', 'I prefer tea.'), cand('c2', 'I always walk.', { conversation_id: 'conv-2' }), cand('c3', 'I never snooze.', { conversation_id: 'conv-2' })]);
    renderApp('#/memory');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Dismiss: I prefer tea/ }));
    await screen.findByText('Dismissed.');
    await waitFor(() => expect(screen.queryByText('I prefer tea.')).toBeNull());
    await user.click(screen.getByRole('button', { name: /Never suggest this again: I always walk/ }));
    await screen.findByText('Dismissed. Reachy will not suggest this again.');
    await user.click(await screen.findByRole('button', { name: 'Forget suggestions from this chat' }));
    await screen.findByText('Removed 1 suggestion from that conversation.');
    const posts = hub.seen.filter((s) => s.method === 'POST');
    expect(posts.map((p) => [p.path, p.body])).toEqual([
      ['/memory-candidates/c1/reject', { suppress: false }], ['/memory-candidates/c2/reject', { suppress: true }],
      ['/memory-candidates/forget-conversation', { conversation_id: 'conv-2' }],
    ]);
    expect(screen.queryByRole('button', { name: /delete all|clear all|reject all/i })).toBeNull(); // there is no bulk delete in v1
  });

  it('shows a refusal from the hub as plain text and keeps the suggestion', async () => {
    const hub = hubWith([cand('c1', 'I prefer tea.')]);
    renderApp('#/memory');
    const user = userEvent.setup();
    const save = await screen.findByRole('button', { name: /Save to memory: I prefer tea/ });
    hub.failWith(() => jsonResponse({ detail: '<b>This suggestion was already decided</b>' }, 409));
    await user.click(save);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('<b>This suggestion was already decided</b>');
    expect(document.querySelector('b')).toBeNull();
    expect(screen.getByText('I prefer tea.')).toBeInTheDocument();
  });

  it('explains when collection is off and when the queue is empty', async () => {
    hubWith([], false);
    renderApp('#/memory');
    await screen.findByText('No suggestions are waiting.');
    expect(screen.getByText(/Suggestions are not being collected right now/)).toBeInTheDocument();
  });

  it('shows an error with a retry when the hub is unavailable', async () => {
    const hub = hubWith([]);
    hub.failWith(() => jsonResponse({ detail: 'Memory suggestions unavailable' }, 502), 10);
    renderApp('#/memory');
    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText('Memory suggestions unavailable')).toBeInTheDocument();
  });

  it('rejects a response that does not have the shape the page relies on', () => {
    expect(() => parseCandidates({ candidates: [{ id: 'a' }] })).toThrow(/Unexpected response/);
    expect(() => parseCandidates({ candidates: [{ ...cand('a', 't'), sensitivity: 'secret' }] })).toThrow(/Unexpected response/);
    expect(() => parseCandidates('nope')).toThrow(/Unexpected response/);
    expect(parseCandidates({ candidates: [], capture_enabled: 'yes' }).capture_enabled).toBe(false);
  });
});
