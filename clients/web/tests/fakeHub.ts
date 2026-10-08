import { vi } from 'vitest';

// A stateful stand-in for the hub's /planner routes that follows the behaviour pinned by the
// real-chain tests in services/reachy-hub/tests/test_web_client.py (statuses, 404s, delete result,
// notes search, reminders that cannot be reopened).
export interface FakeTask { id: string; text: string; status: 'open' | 'done'; created_at?: string }
export interface FakeReminder { id: string; text: string; due_at: string; status: 'pending' | 'done' }
export interface FakeNote { id: string; title: string; body: string; updated_at: string }
export interface FakeReceipt { id: string; action_type: string; status: 'success' | 'failed'; at: string; source_channel: string; fields: Record<string, string>; failure_reason: string | null }

export interface FakeAlarm { id: string; label: string; due_at: string; station_id: string | null; status: string; volume: number; repeat: number[]; enabled: boolean; delivery: string | null }
export interface FakeStation { id: string; name: string; guide_id: string }

export interface FakeTurn { id: string; text: string; reply: string | null; status: 'pending' | 'complete' | 'unknown'; web_search: unknown }
export interface FakeChat { id: string; user_id: string; title: string; created_at: string; updated_at: string; turns: FakeTurn[] }
export type Replier = (text: string, body: any) => { reply: string; web_search?: unknown; context_meeting?: string | null };

export interface FakeMeeting {
  id: string; title: string; description?: string | null; status: string; created_at: string; project_scope?: string | null; participants?: string[];
  context?: string | null; duration_seconds?: number | null; error_detail?: string | null; transcript_segments?: any[] | null; diarization_segments?: any[] | null;
  aligned_segments?: any[] | null; audio_gaps?: any; speaker_names?: Record<string, string>; transcript_corrections?: Record<string, string>;
  summary?: any; minutes?: any;
}

export interface Deferred { resolve(response: Response): void; request: { path: string; method: string; signal?: AbortSignal | null } }

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

export function createFakeHub(seed: { tasks?: FakeTask[]; reminders?: FakeReminder[]; notes?: FakeNote[]; receipts?: FakeReceipt[]; alarms?: FakeAlarm[]; stations?: FakeStation[]; search?: unknown[]; chats?: FakeChat[]; reply?: Replier; meetings?: FakeMeeting[]; status?: unknown } = {}) {
  const data = {
    tasks: seed.tasks ?? [],
    reminders: seed.reminders ?? [],
    notes: seed.notes ?? [],
    receipts: seed.receipts ?? [],
    alarms: seed.alarms ?? [],
    stations: seed.stations ?? [],
    search: seed.search ?? [],
    stopped: false,
    deepInfo: { configured: true, available: true, reason: null, eta_seconds: 330 } as any,
    chats: seed.chats ?? [],
    meetings: (seed.meetings ?? []) as FakeMeeting[],
    llm: { local: { provider: 'openai-compatible', base_url: 'http://ovms/v1', model: 'qwen', api_key: null as string | null }, cloud: null as any, routing: { mode: 'local_only' } } as any,
    persona: { name: 'Reachy', system_prompt: 'You are Reachy.', location: null, timezone: 'UTC', tone: 'default' } as any,
    websearch: { policy: 'off', hosted: { brave: { enabled: false, api_key: null, monthly_limit: 900 }, exa: { enabled: false, api_key: null, monthly_limit: 900 }, tavily: { enabled: false, api_key: null, monthly_limit: 900 } }, fallback: 'builtin_searxng', base_url: null, api_key: null, result_count: 5 } as any,
    searchLog: { usage: { period: '2030-01', used: { brave: 3, exa: 0, tavily: 0 }, limits: { brave: 900, exa: 900, tavily: 900 }, enabled: { brave: true, exa: false, tavily: false } }, entries: [] as any[] },
    secrets: [] as string[], // every key the page ever sent, so a test can assert none came back
    saves: [] as { call: string; body: any }[],
    deepJobs: [] as any[],
    suggestions: { suggestions: [], terms_used: 0, truncated: false } as any,
    sessions: new Map<string, { interaction_mode: string; dnd: boolean; active_channel: string }>(),
    messages: [] as any[],
    reply: seed.reply ?? (((text: string) => ({ reply: `Reply to: ${text}` })) as Replier),
  };
  const calls: string[] = [];
  const bodies: { call: string; body: unknown }[] = [];
  let counter = 0;
  const held: { matcher: (call: string) => boolean; pending: Deferred[]; ignoreAbort: boolean }[] = [];
  const overrides: { matcher: (call: string) => boolean; make: () => Response }[] = [];
  let user: string | null = 'owner';
  const nextId = (p: string) => `${p}${++counter}`;

  const meetingRoute = (method: string, path: string, body: any): Response => {
    const full = (m: FakeMeeting) => ({
      description: null, project_scope: null, participants: [], context: null, duration_seconds: null, error_detail: null, transcript_segments: null,
      diarization_segments: null, aligned_segments: null, audio_gaps: null, speaker_names: {}, transcript_corrections: {}, summary: null, minutes: null, ...m,
    });
    if (path === '/meetings' && method === 'GET') return jsonResponse(data.meetings.map(full));
    if (path === '/meetings' && method === 'POST') {
      const m: FakeMeeting = { id: nextId('m'), title: body.title, status: 'uploaded', created_at: new Date().toISOString(), participants: String(body.participants || '').split(',').map((p: string) => p.trim()).filter(Boolean), project_scope: body.project_scope || null, context: body.context || null };
      data.meetings.unshift(m);
      return jsonResponse(full(m));
    }
    if (path === '/deep-review/info') return jsonResponse(data.deepInfo);
    if (path === '/deep-review/current') return jsonResponse(data.deepJobs.find((j: any) => j.status !== 'done' && j.status !== 'failed') ?? null);
    let d = path.match(/^\/deep-review\/([^/]+)$/);
    if (d) {
      const job = data.deepJobs.find((j: any) => j.id === d![1]);
      return job ? jsonResponse(job) : jsonResponse({ detail: 'no such job' }, 404);
    }
    const m = path.match(/^\/meetings\/([^/]+)(\/.*)?$/);
    const meeting = m && data.meetings.find((x) => x.id === decodeURIComponent(m[1]!));
    if (!m || !meeting) return jsonResponse({ detail: 'Meeting not found' }, 404);
    const rest = m[2] ?? '';
    if (rest === '' && method === 'GET') return jsonResponse(full(meeting));
    if (rest === '' && method === 'DELETE') {
      if (!['complete', 'failed', 'cancelled', 'aligning'].includes(meeting.status)) return jsonResponse({ detail: 'Meeting is still being processed' }, 409);
      data.meetings = data.meetings.filter((x) => x !== meeting);
      return jsonResponse({ deleted: true });
    }
    if (rest === '/cancel') {
      meeting.status = 'cancelled';
      return jsonResponse(full(meeting));
    }
    if (rest === '/speakers') {
      meeting.speaker_names = { ...(meeting.speaker_names ?? {}) };
      for (const [k, v] of Object.entries(body.names as Record<string, string>)) (v ? (meeting.speaker_names[k] = v) : delete meeting.speaker_names[k]);
      return jsonResponse(full(meeting));
    }
    if (rest === '/title') {
      Object.assign(meeting, { title: body.title, description: body.description || null });
      return jsonResponse(full(meeting));
    }
    if (rest === '/describe') {
      Object.assign(meeting, { title: 'Generated title', description: 'Generated description.' });
      return jsonResponse(full(meeting));
    }
    const c = rest.match(/^\/corrections\/(\d+)$/);
    if (c) {
      meeting.transcript_corrections = { ...(meeting.transcript_corrections ?? {}) };
      if (method === 'PUT') meeting.transcript_corrections[c[1]!] = body.text;
      else delete meeting.transcript_corrections[c[1]!];
      return jsonResponse(full(meeting));
    }
    if (rest === '/corrections/replace') {
      let n = 0;
      meeting.transcript_corrections = { ...(meeting.transcript_corrections ?? {}) };
      (meeting.transcript_segments ?? []).forEach((s: any, i: number) => {
        const text = meeting.transcript_corrections![String(i)] ?? s.text;
        if (text.includes(body.find)) { meeting.transcript_corrections![String(i)] = text.replaceAll(body.find, body.replace); n += 1; }
      });
      return jsonResponse({ replaced_segments: n });
    }
    if (rest === '/corrections/suggest') return jsonResponse(data.suggestions);
    if (rest === '/corrections/deep-review' || /^\/outputs\/(summary|minutes)\/deep$/.test(rest)) {
      const job = { id: nextId('job'), status: 'running', stage: 'Loading the larger model', task: rest.includes('outputs') ? rest.split('/')[2] : 'corrections', meeting_id: meeting.id, meeting_title: meeting.title, reachy_unavailable: true, reachy_online: false, error: null, result: null };
      data.deepJobs.push(job);
      return jsonResponse(job, 202);
    }
    const o = rest.match(/^\/outputs\/(summary|minutes)$/);
    if (o) {
      const kind = o[1] as 'summary' | 'minutes';
      meeting[kind] = method === 'DELETE' ? null : { text: `Generated ${kind} via ${body.model}`, tier: body.model, generated_at: new Date().toISOString() };
      return jsonResponse(full(meeting));
    }
    return jsonResponse({ detail: 'Not Found' }, 404);
  };

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
    if (path === '/chats' && method === 'GET') {
      const mine = data.chats.filter((c) => c.user_id === query.get('user_id'));
      return jsonResponse(mine.map(({ turns: _t, ...rest }) => rest));
    }
    if (path === '/chats' && method === 'POST') {
      const now = new Date().toISOString();
      const chat: FakeChat = { id: nextId('c'), user_id: body.user_id, title: body.title, created_at: now, updated_at: now, turns: [] };
      data.chats.unshift(chat);
      const { turns: _t, ...rest } = chat;
      return jsonResponse(rest);
    }
    m = path.match(/^\/chats\/([^/]+)$/);
    if (m) {
      const chat = data.chats.find((c) => c.id === m![1] && c.user_id === query.get('user_id'));
      if (!chat) return jsonResponse({ detail: 'Chat not found' }, 404);
      if (method === 'DELETE') {
        data.chats = data.chats.filter((c) => c !== chat);
        return jsonResponse({ deleted: true });
      }
      return jsonResponse(chat);
    }
    if (path === '/messages' && method === 'POST') {
      data.messages.push(body);
      const out = data.reply(body.text, body);
      const chat = data.chats.find((c) => c.id === body.chat_id);
      chat?.turns.push({ id: nextId('turn'), text: body.text, reply: out.reply, status: 'complete', web_search: out.web_search ?? null });
      data.sessions.set(body.user_id, { interaction_mode: 'office', dnd: true, active_channel: 'web' });
      return jsonResponse({ web_search: null, context_meeting: null, ...out });
    }
    m = path.match(/^\/sessions\/([^/]+)$/);
    if (m) {
      const info = data.sessions.get(decodeURIComponent(m[1]!));
      return info ? jsonResponse(info) : jsonResponse({ detail: `no session for user '${m[1]}'` }, 404);
    }
    if (path.startsWith('/meetings') || path.startsWith('/deep-review')) return meetingRoute(method, path, body);
    if (path === '/settings/llm') {
      if (method === 'PUT') {
        data.saves.push({ call: 'llm', body });
        const mask = (k: string) => `********${k.slice(-4)}`;
        const apply = (name: 'local' | 'cloud') => {
          const next = body[name];
          if (!next) return null;
          const old = data.llm[name];
          const key = 'api_key' in next ? (next.api_key === null ? null : (data.secrets.push(next.api_key), mask(next.api_key))) : (old?.api_key ?? null);
          return { provider: 'openai-compatible', base_url: next.base_url, model: next.model, api_key: key };
        };
        data.llm = { local: apply('local'), cloud: apply('cloud'), routing: body.routing };
      }
      return jsonResponse({ ...data.llm, updated_at: '2030-01-01T00:00:00Z' });
    }
    if (path === '/settings/persona') {
      if (method === 'PUT') {
        if (!body.name) return jsonResponse({ detail: [{ msg: 'too short' }] }, 422);
        data.persona = { ...body };
      }
      return jsonResponse(data.persona);
    }
    if (path === '/settings/websearch') {
      if (method === 'PUT') {
        data.saves.push({ call: 'websearch', body });
        const cfg = data.websearch;
        for (const [name, h] of Object.entries<any>(body.hosted ?? {})) {
          const o = cfg.hosted[name];
          if ('api_key' in h) o.api_key = h.api_key === null ? null : (data.secrets.push(h.api_key), `********${h.api_key.slice(-4)}`);
          o.enabled = h.enabled; if (h.monthly_limit) o.monthly_limit = h.monthly_limit;
        }
        for (const k of ['policy', 'fallback', 'base_url', 'result_count']) if (k in body) cfg[k] = body[k];
        if ('api_key' in body) cfg.api_key = body.api_key === null ? null : (data.secrets.push(body.api_key), `********${body.api_key.slice(-4)}`);
      }
      return jsonResponse({ ...data.websearch, usage: { period: data.searchLog.usage.period, used: data.searchLog.usage.used } });
    }
    if (path === '/websearch/log') return jsonResponse(data.searchLog);
    m = path.match(/^\/sessions\/([^/]+)\/(mode|dnd)$/);
    if (m) {
      const info = data.sessions.get(decodeURIComponent(m[1]!));
      if (!info) return jsonResponse({ detail: `no session for user '${m[1]}'` }, 404);
      if (m[2] === 'mode') info.interaction_mode = body.interaction_mode; else info.dnd = body.dnd;
      return jsonResponse(info);
    }
    if (path === '/planner/receipts') return jsonResponse(data.receipts);
    if (path === '/planner/alarms' && method === 'GET') return jsonResponse(data.alarms);
    if (path === '/planner/alarms' && method === 'POST') {
      const [h, min] = String(body.time).split(':').map(Number);
      const due = new Date();
      due.setHours(h!, min!, 0, 0);
      if (due.getTime() <= Date.now()) due.setDate(due.getDate() + 1);
      const alarm: FakeAlarm = { id: nextId('a'), status: 'scheduled', enabled: true, delivery: null, ...body, due_at: due.toISOString() };
      delete (alarm as any).time;
      data.alarms.push(alarm);
      return jsonResponse(alarm);
    }
    if (path === '/planner/alarms/stop') {
      data.stopped = true;
      return jsonResponse({ stopped: true });
    }
    m = path.match(/^\/planner\/alarms\/([^/]+)$/);
    if (m) {
      const alarm = data.alarms.find((a) => a.id === m![1]);
      if (!alarm) return jsonResponse({ detail: `no alarm '${m[1]}'` }, 404);
      if (method === 'DELETE') alarm.status = 'cancelled';
      else {
        const { time, ...rest } = body;
        Object.assign(alarm, rest);
        if (time) {
          const [h, min] = String(time).split(':').map(Number);
          const due = new Date(alarm.due_at);
          due.setHours(h!, min!, 0, 0);
          alarm.due_at = due.toISOString();
        }
      }
      return jsonResponse(alarm);
    }
    if (path === '/planner/stations' && method === 'GET') return jsonResponse(data.stations);
    if (path === '/planner/stations' && method === 'POST') {
      const station: FakeStation = { id: nextId('s'), name: body.name, guide_id: body.guide_id };
      data.stations.push(station);
      return jsonResponse(station);
    }
    if (path === '/planner/stations/search') return jsonResponse(data.search);
    m = path.match(/^\/planner\/stations\/([^/]+)$/);
    if (m) {
      data.stations = data.stations.filter((st) => st.id !== m![1]);
      return jsonResponse({ deleted: true });
    }
    return jsonResponse({ detail: 'Not Found' }, 404);
  };

  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://hub.test');
      const method = init?.method ?? 'GET';
      const call = `${method} ${url.pathname}${url.search}`;
      const rawBody = init?.body;
      const body =
        rawBody instanceof FormData
          ? Object.fromEntries([...rawBody.entries()].map(([k, v]) => [k, v instanceof File ? `file:${v.name}` : v]))
          : rawBody
            ? JSON.parse(String(rawBody))
            : undefined;
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
