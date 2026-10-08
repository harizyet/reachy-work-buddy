import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { request } from '../src/api/client';
import { SAVE_DELAY_MS } from '../src/features/notes/useNotesEditor';
import { createFakeHub, jsonResponse, type FakeHub } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

// Authentication-generation isolation (Phase 47B). Each case starts a request in one session and lets
// its answer arrive after the session has ended or changed. The answer must not restore signed-in UI,
// reach the query cache, trigger follow-up requests, or sign out a newer session.

const SECRET = 'SECRET-CLIENT-LIST';
const wait = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

beforeEach(() => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'], shouldAdvanceTime: true }));
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function hubWithSecrets(): FakeHub {
  return createFakeHub({
    status: SAMPLE_STATUS,
    tasks: [{ id: 't1', text: SECRET, status: 'open' }],
    reminders: [{ id: 'r1', text: SECRET, due_at: new Date(Date.now() + 86_400_000).toISOString(), status: 'pending' }],
    notes: [{ id: 'n1', title: SECRET, body: 'private body', updated_at: new Date().toISOString() }],
  });
}

const setup = () => userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTimeAsync(ms) });
const logout = (user: ReturnType<typeof setup>) => user.click(screen.getByRole('button', { name: 'Log out' }));
const signInAgain = async (user: ReturnType<typeof setup>, name = 'owner') => {
  await user.type(await screen.findByLabelText('Username'), name);
  await user.type(screen.getByLabelText('Password'), 'pw');
  await user.click(screen.getByRole('button', { name: 'Sign in' }));
};
const cachedData = (client: ReturnType<typeof renderApp>['client']) =>
  client.getQueryCache().getAll().filter((q) => q.state.data !== undefined);

describe.each([
  ['the request is aborted, as a browser does', false],
  ['the response was already in hand (abort too late)', true],
])('a list response that arrives after logout: %s', (_name, ignoreAbort) => {
  it('is discarded: no secret in the page, no cached data, no follow-up request', async () => {
    const hub = hubWithSecrets();
    const pending = hub.hold((c) => c === 'GET /planner/tasks', { ignoreAbort });
    const { client } = renderApp('#/todo');
    const user = setup();
    await waitFor(() => expect(pending).toHaveLength(1));

    await logout(user);
    expect(await screen.findByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();
    expect(pending[0]!.request.signal?.aborted).toBe(true);

    const before = hub.calls.length;
    await act(async () => pending[0]!.resolve(jsonResponse(hub.data.tasks)));
    await wait(50);
    expect(screen.getByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(SECRET);
    expect(cachedData(client)).toHaveLength(0);
    expect(hub.calls.slice(before)).toEqual([]);
  });
});

describe('after the session expires (a 401 elsewhere)', () => {
  it('a data response from before the expiry does not bring the signed-in page back', async () => {
    const hub = hubWithSecrets();
    const pending = hub.hold((c) => c === 'GET /planner/tasks', { ignoreAbort: true });
    const { client } = renderApp('#/todo');
    await waitFor(() => expect(pending).toHaveLength(1));
    hub.respond((c) => c === 'GET /expired-probe', () => jsonResponse({ detail: 'Login required' }, 401));
    await act(async () => { await request('/expired-probe').catch(() => undefined); });
    expect(await screen.findByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Your session has ended');

    await act(async () => pending[0]!.resolve(jsonResponse(hub.data.tasks)));
    await wait(50);
    expect(screen.getByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(SECRET);
    expect(cachedData(client)).toHaveLength(0);
  });

  it('a slow /auth/me that says "signed in" cannot undo the expiry', async () => {
    const hub = hubWithSecrets();
    const me = hub.hold((c) => c === 'GET /auth/me', { ignoreAbort: true });
    renderApp('#/');
    await waitFor(() => expect(me).toHaveLength(1));
    hub.respond((c) => c === 'GET /expired-probe', () => jsonResponse({ detail: 'Login required' }, 401));
    await act(async () => { await request('/expired-probe').catch(() => undefined); });
    expect(await screen.findByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();

    await act(async () => me[0]!.resolve(jsonResponse({ username: 'owner' })));
    await wait(50);
    expect(screen.getByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();
    expect(screen.queryByText('System status')).not.toBeInTheDocument();
  });
});

describe('across a logout and a new sign-in', () => {
  it('a late 401 from the old session does not sign out the new one', async () => {
    const hub = hubWithSecrets();
    const pending = hub.hold((c) => c === 'GET /planner/reminders', { ignoreAbort: true });
    renderApp('#/reminders');
    const user = setup();
    await waitFor(() => expect(pending).toHaveLength(1));
    await logout(user);
    await signInAgain(user);
    expect(await screen.findByRole('heading', { name: 'System status' })).toBeInTheDocument();

    await act(async () => pending[0]!.resolve(jsonResponse({ detail: 'Login required' }, 401)));
    await wait(50);
    expect(screen.getByRole('heading', { name: 'System status' })).toBeInTheDocument();
    expect(screen.queryByText(/session has ended/)).not.toBeInTheDocument();
  });

  it('a late success from the old session does not fill the new one', async () => {
    const hub = hubWithSecrets();
    const tasksCall = (c: string) => c === 'GET /planner/tasks';
    const old = hub.hold(tasksCall, { ignoreAbort: true });
    const { client } = renderApp('#/todo');
    const user = setup();
    await waitFor(() => expect(old).toHaveLength(1));
    await logout(user);
    hub.release(tasksCall); // only the old session's request was slow
    await signInAgain(user, 'other');
    await screen.findByRole('heading', { name: 'System status' });
    hub.data.tasks = []; // the second owner has no tasks
    await user.click(screen.getByRole('link', { name: 'To Do' }));
    await screen.findByText('Nothing to do yet.');

    await act(async () => old[0]!.resolve(jsonResponse([{ id: 't1', text: SECRET, status: 'open' }])));
    await wait(50);
    expect(screen.getByText('Nothing to do yet.')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(SECRET);
    expect(JSON.stringify(client.getQueryCache().getAll().map((q) => q.state.data))).not.toContain(SECRET);
  });

  it('the next session starts from an empty cache: nothing of the previous owner shows while it loads', async () => {
    const hub = hubWithSecrets();
    renderApp('#/todo');
    const user = setup();
    expect(await screen.findByText(SECRET)).toBeInTheDocument();
    await logout(user);
    hub.hold((c) => c === 'GET /planner/tasks'); // the new owner's list is slow
    await signInAgain(user, 'other');
    await screen.findByRole('heading', { name: 'System status' });
    await user.click(screen.getByRole('link', { name: 'To Do' }));
    await screen.findByText('Loading…');
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it('a mutation answered after logout triggers no reload and leaves nothing behind', async () => {
    const hub = hubWithSecrets();
    const { client } = renderApp('#/todo');
    const user = setup();
    await screen.findByText(SECRET);
    const post = hub.hold((c) => c === 'POST /planner/tasks', { ignoreAbort: true });
    await user.click(screen.getByRole('button', { name: /New Reminder/ }));
    await user.type(screen.getByRole('textbox', { name: 'New to-do' }), 'late addition{Enter}');
    await waitFor(() => expect(post).toHaveLength(1));
    await logout(user);
    const before = hub.calls.length;

    await act(async () => post[0]!.resolve(jsonResponse({ id: 't9', text: 'late addition', status: 'open' })));
    await wait(50);
    expect(hub.calls.slice(before)).toEqual([]); // no invalidation refetch
    expect(screen.getByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/late addition|SECRET/);
    expect(cachedData(client)).toHaveLength(0);
  });
});

describe('Notes editor and logout', () => {
  async function openNote(user: ReturnType<typeof setup>) {
    await user.click(await screen.findByRole('button', { name: new RegExp(SECRET) }));
    await user.type(screen.getByRole('textbox', { name: 'Note' }), ' more');
  }

  it('an edit not yet saved when the owner logs out is dropped, not sent', async () => {
    const hub = hubWithSecrets();
    renderApp('#/notes');
    const user = setup();
    await openNote(user);
    await logout(user); // inside the 700 ms window
    await screen.findByRole('heading', { name: 'Sign in to Reachy' });
    await wait(SAVE_DELAY_MS * 3);
    expect(hub.calls.some((c) => c.startsWith('PUT') || c.startsWith('POST /planner'))).toBe(false);
  });

  it('a save in flight at logout is disowned: no "Saved", no cache entry, no stray errors', async () => {
    const hub = hubWithSecrets();
    const put = hub.hold((c) => c === 'PUT /planner/notes/n1', { ignoreAbort: true });
    const { client } = renderApp('#/notes');
    const user = setup();
    await openNote(user);
    await wait(SAVE_DELAY_MS + 50);
    await waitFor(() => expect(put).toHaveLength(1));
    await logout(user);
    const unhandled = vi.fn();
    process.on('unhandledRejection', unhandled);

    await act(async () => put[0]!.resolve(jsonResponse({ id: 'n1', title: SECRET, body: 'private body more', updated_at: new Date().toISOString() })));
    await wait(100);
    process.off('unhandledRejection', unhandled);
    expect(unhandled).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Saved|private body/);
    expect(cachedData(client)).toHaveLength(0);
  });

  it('leaving the Notes page while signed in still saves a late edit', async () => {
    const hub = hubWithSecrets();
    renderApp('#/notes');
    const user = setup();
    await openNote(user);
    await user.click(screen.getByRole('link', { name: 'To Do' }));
    await waitFor(() => expect(hub.calls).toContain('PUT /planner/notes/n1'));
  });
});

describe('Chat and logout', () => {
  const chatHub = () =>
    createFakeHub({
      status: { ...SAMPLE_STATUS, default_user_id: 'owner-user' },
      chats: [{ id: 'c1', user_id: 'owner-user', title: SECRET, created_at: '2030-01-01T00:00:00Z', updated_at: '2030-01-01T00:00:00Z', turns: [] }],
    });
  const box = () => screen.getByRole('textbox', { name: 'Message' });

  it('a reply that arrives after logout is not shown, even after signing back in', async () => {
    const hub = chatHub();
    const post = hub.hold((c) => c === 'POST /messages', { ignoreAbort: true });
    renderApp('#/chat');
    const user = setup();
    await waitFor(() => expect(box()).toBeEnabled());
    await user.type(box(), 'private question{Enter}');
    await waitFor(() => expect(post).toHaveLength(1));
    await logout(user);
    hub.release((c) => c === 'POST /messages');
    await act(async () => post[0]!.resolve(jsonResponse({ reply: 'SECRET-REPLY', web_search: null, context_meeting: null })));
    await wait(50);
    expect(screen.getByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/SECRET-REPLY|private question/);

    await signInAgain(user);
    await user.click(await screen.findByRole('link', { name: 'Chat' }));
    await waitFor(() => expect(box()).toBeEnabled());
    expect(document.body.textContent).not.toMatch(/SECRET-REPLY|private question/);
  });

  it('chat history requested before logout never reaches the next session', async () => {
    const hub = chatHub();
    const list = hub.hold((c) => c.startsWith('GET /chats?'), { ignoreAbort: true });
    const { client } = renderApp('#/chat');
    const user = setup();
    await waitFor(() => expect(list).toHaveLength(1));
    await logout(user);
    hub.release((c) => c.startsWith('GET /chats?'));
    await act(async () => list[0]!.resolve(jsonResponse(hub.data.chats.map(({ turns: _t, ...c }) => c))));
    await wait(50);
    expect(document.body.textContent).not.toContain(SECRET);
    expect(cachedData(client)).toHaveLength(0);
  });

  it('a message typed but not sent is gone after logout and sign-in', async () => {
    chatHub();
    renderApp('#/chat');
    const user = setup();
    await waitFor(() => expect(box()).toBeEnabled());
    await user.type(box(), 'half-written secret');
    await logout(user);
    await signInAgain(user);
    await user.click(await screen.findByRole('link', { name: 'Chat' }));
    await waitFor(() => expect(box()).toBeEnabled());
    expect(box()).toHaveValue('');
  });
});

describe('Meetings and logout', () => {
  const meetingHub = () =>
    createFakeHub({
      status: SAMPLE_STATUS,
      meetings: [{ id: 'm1', title: SECRET, status: 'complete', created_at: '2030-01-01T00:00:00Z', transcript_segments: [{ start: 0, end: 1, text: 'private words' }] }],
    });

  it('a meeting detail requested before logout never reaches the page or the cache', async () => {
    const hub = meetingHub();
    const detail = hub.hold((c) => c === 'GET /meetings/m1', { ignoreAbort: true });
    const { client } = renderApp('#/meetings/m1');
    const user = setup();
    await waitFor(() => expect(detail).toHaveLength(1));
    await logout(user);
    hub.release((c) => c === 'GET /meetings/m1');
    await act(async () => detail[0]!.resolve(jsonResponse({ ...hub.data.meetings[0], participants: [], speaker_names: {}, transcript_corrections: {} })));
    await wait(50);
    expect(document.body.textContent).not.toMatch(/SECRET|private words/);
    expect(cachedData(client)).toHaveLength(0);
  });

  it('an upload that finishes after logout does not refresh a list nobody is looking at', async () => {
    const hub = meetingHub();
    const post = hub.hold((c) => c === 'POST /meetings', { ignoreAbort: true });
    renderApp('#/meetings');
    const user = setup();
    await user.type(await screen.findByLabelText('Title'), 'Standup');
    await user.upload(screen.getByLabelText(/Recording file/), new File(['RIFF'], 'a.wav', { type: 'audio/wav' }));
    await user.click(screen.getByRole('button', { name: 'Upload meeting' }));
    await waitFor(() => expect(post).toHaveLength(1));
    await logout(user);
    const before = hub.calls.length;
    await act(async () => post[0]!.resolve(jsonResponse({ id: 'm9', title: 'Standup', status: 'uploaded', created_at: '2030-01-01T00:00:00Z' })));
    await wait(50);
    expect(hub.calls.slice(before)).toEqual([]);
    expect(screen.getByRole('heading', { name: 'Sign in to Reachy' })).toBeInTheDocument();
  });

  it('stops following a deep review when the owner signs out', async () => {
    const hub = meetingHub();
    hub.data.deepJobs.push({ id: 'job1', status: 'running', stage: 'Working', task: 'summary', meeting_id: 'm1', meeting_title: 'X', reachy_unavailable: true, reachy_online: false, error: null, result: null });
    renderApp('#/meetings');
    const user = setup();
    await screen.findByText('Working');
    await logout(user);
    expect(screen.queryByText('Working')).not.toBeInTheDocument();
    const before = hub.calls.length;
    await wait(20_000);
    expect(hub.calls.slice(before).filter((c) => c.includes('deep-review'))).toEqual([]);
  });
});
