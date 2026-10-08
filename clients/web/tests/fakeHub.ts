import { vi } from 'vitest';

// A stateful stand-in for the hub's /planner routes that follows the behaviour pinned by the
// real-chain tests in services/reachy-hub/tests/test_web_client.py (statuses, 404s, delete result,
// notes search, reminders that cannot be reopened).
export interface FakeTask { id: string; text: string; status: 'open' | 'done'; created_at?: string }
export interface FakeReminder { id: string; text: string; due_at: string; status: 'pending' | 'done' }
export interface FakeNote { id: string; title: string; body: string; updated_at: string }
export interface FakeReceipt { id: string; action_type: string; status: 'success' | 'failed'; at: string; source_channel: string; fields: Record<string, string>; failure_reason: string | null }

export interface Deferred { resolve(response: Response): void; request: { path: string; method: string; signal?: AbortSignal | null } }

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

export function createFakeHub(seed: { tasks?: FakeTask[]; reminders?: FakeReminder[]; notes?: FakeNote[]; receipts?: FakeReceipt[]; status?: unknown } = {}) {
  const data = {
    tasks: seed.tasks ?? [],
    reminders: seed.reminders ?? [],
    notes: seed.notes ?? [],
    receipts: seed.receipts ?? [],
  };
  const calls: string[] = [];
  const bodies: { call: string; body: unknown }[] = [];
  let counter = 0;
  const held: { matcher: (call: string) => boolean; pending: Deferred[]; ignoreAbort: boolean }[] = [];
  const overrides: { matcher: (call: string) => boolean; make: () => Response }[] = [];
  let user: string | null = 'owner';
  const nextId = (p: string) => `${p}${++counter}`;

  const route = (method: string, path: string, query: URLSearchParams, body: any): Response => {
    if (path === '/auth/me') return user ? jsonResponse({ username: user }) : jsonResponse({ detail: 'Login required' }, 401);
    if (path === '/auth/logout') {
      user = null;
      return jsonResponse({ ok: true });
    }
    if (path === '/auth/login') {
      user = body.username;
      return jsonResponse({ username: user });
    }
    if (!user) return jsonResponse({ detail: 'Login required' }, 401);
    if (path === '/status') return jsonResponse(seed.status);
    if (path === '/planner/tasks' && method === 'GET') return jsonResponse(data.tasks);
    if (path === '/planner/tasks' && method === 'POST') {
      const task: FakeTask = { id: nextId('t'), text: body.text, status: 'open' };
      data.tasks.push(task);
      return jsonResponse(task);
    }
    let m = path.match(/^\/planner\/tasks\/([^/]+)(?:\/(complete|reopen))?$/);
    if (m) {
      const task = data.tasks.find((t) => t.id === m![1]);
      if (!task) return jsonResponse({ detail: `no task '${m[1]}'` }, 404);
      if (method === 'DELETE') data.tasks = data.tasks.filter((t) => t !== task);
      else if (method === 'PUT') task.text = body.text;
      else task.status = m[2] === 'complete' ? 'done' : 'open';
      return jsonResponse(method === 'DELETE' ? { deleted: true } : task);
    }
    if (path === '/planner/reminders' && method === 'GET') return jsonResponse(data.reminders);
    if (path === '/planner/reminders' && method === 'POST') {
      const reminder: FakeReminder = { id: nextId('r'), text: body.text, due_at: body.due_at, status: 'pending' };
      data.reminders.push(reminder);
      return jsonResponse(reminder);
    }
    m = path.match(/^\/planner\/reminders\/([^/]+)(?:\/(complete))?$/);
    if (m) {
      const reminder = data.reminders.find((r) => r.id === m![1]);
      if (!reminder) return jsonResponse({ detail: `no reminder '${m[1]}'` }, 404);
      if (method === 'DELETE') data.reminders = data.reminders.filter((r) => r !== reminder);
      else reminder.status = 'done';
      return jsonResponse(method === 'DELETE' ? { deleted: true } : reminder);
    }
    if (path === '/planner/notes' && method === 'GET') {
      const q = (query.get('q') ?? '').toLowerCase();
      return jsonResponse(data.notes.filter((n) => !q || n.title.toLowerCase().includes(q) || n.body.toLowerCase().includes(q)));
    }
    if (path === '/planner/notes' && method === 'POST') {
      const note: FakeNote = { id: nextId('n'), title: body.title, body: body.body ?? '', updated_at: new Date().toISOString() };
      data.notes.push(note);
      return jsonResponse(note);
    }
    m = path.match(/^\/planner\/notes\/([^/]+)$/);
    if (m) {
      const note = data.notes.find((n) => n.id === m![1]);
      if (!note) return jsonResponse({ detail: `no note '${m[1]}'` }, 404);
      if (method === 'DELETE') {
        data.notes = data.notes.filter((n) => n !== note);
        return jsonResponse({ deleted: true });
      }
      Object.assign(note, { title: body.title, body: body.body ?? '', updated_at: new Date().toISOString() });
      return jsonResponse(note);
    }
    if (path === '/planner/receipts') return jsonResponse(data.receipts);
    return jsonResponse({ detail: 'Not Found' }, 404);
  };

  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://hub.test');
      const method = init?.method ?? 'GET';
      const call = `${method} ${url.pathname}${url.search}`;
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push(call);
      if (body !== undefined) bodies.push({ call, body });
      const override = overrides.find((o) => o.matcher(call));
      if (override) return override.make();
      const hold = held.find((h) => h.matcher(call));
      if (hold) {
        // The request is parked until the test releases it, and the answer is computed then, as a slow server would.
        return new Promise<Response>((resolve, reject) => {
          const entry: Deferred = {
            resolve: (response) => resolve(response),
            request: { path: call, method, signal: init?.signal },
          };
          // A real browser rejects an aborted fetch; `ignoreAbort` models a response already in hand when the abort came.
          if (!hold.ignoreAbort) init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
          hold.pending.push(entry);
        });
      }
      return route(method, url.pathname, url.searchParams, body);
    }),
  );

  return {
    data,
    calls,
    bodies,
    signIn: (name = 'owner') => { user = name; },
    signOutServerSide: () => { user = null; },
    /** Park every request whose "METHOD /path?query" matches; release with `pending[i].resolve(...)`. */
    hold(matcher: (call: string) => boolean, options: { ignoreAbort?: boolean } = {}): Deferred[] {
      const entry = { matcher, pending: [] as Deferred[], ignoreAbort: options.ignoreAbort ?? false };
      held.push(entry);
      return entry.pending;
    },
    release(matcher: (call: string) => boolean) {
      const index = held.findIndex((h) => h.matcher === matcher);
      if (index >= 0) held.splice(index, 1);
    },
    /** Answer matching requests with a fixed response (a server failure, say) until `clearOverrides()`. */
    respond(matcher: (call: string) => boolean, make: () => Response) {
      overrides.push({ matcher, make });
    },
    clearOverrides() {
      overrides.length = 0;
    },
  };
}

export type FakeHub = ReturnType<typeof createFakeHub>;
