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
    audit: [] as any[],
    queued: [] as any[],
    coding: { projects: [] as any[], sessions: [] as any[], terminal: [] as any[], allowance: { source: '', windows: [] as any[] }, events: {} as Record<string, any[]>, usage: {} as Record<string, any[]>, starts: [] as any[] },
    recognition: { benchmark_enabled: false, reauthenticated: false, reauth_expires_in_seconds: 0, voice_samples: [] as any[], face_samples: [] as any[] } as any,
    google: { configured: false, client_type: null as string | null, identity: null as any, capabilities: { gmail: { status: 'disconnected', enabled: false, last_success: null }, calendar: { status: 'disconnected', enabled: false, last_success: null } }, scopes: [] as string[], selected_calendars: [] as string[] } as any,
    googleCalls: [] as { call: string; body: any }[],
    calendars: [{ id: 'cal1', name: 'Work', timezone: 'Asia/Singapore' }, { id: 'cal2', name: 'Home', timezone: 'UTC' }] as any[],
    events: [] as any[],
    busy: [] as any[],
    mail: [] as any[],
    mailBodies: {} as Record<string, any>,
    credentials: [] as any[],
    revoked: true,
    robots: [{ robot_id: 'desk', online: true, voice_capable: true, wake_capable: true, wake_armed: false, wake_counts: { candidates: 0, admitted: 0, rejected: {} } }] as any[],
    voiceSession: null as any,
    motion: { conversation_motion: false, speech_wobble: false, conversation_active: false } as any,
    motionWrites: [] as any[],
    authUrl: null as string | null,
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
    if (path === '/robots' && method === 'GET') return jsonResponse(data.robots.map((r: any) => ({ robot_id: r.robot_id, base_url: 'http://robot' })));
    if (path === '/robot-voice') return jsonResponse({ robots: data.robots, session: data.voiceSession });
    if (path === '/robot-voice/start') {
      const robot = data.robots.find((r: any) => r.robot_id === body.robot_id);
      if (!robot?.online) return jsonResponse({ detail: 'Robot is not connected to the hub' }, 409);
      data.voiceSession = { voice_session_id: 'vs1', state: 'listening', stop_reason: null, last_error: null, wake_started: false, turns: [], started_for: body.user_id };
      return jsonResponse(data.voiceSession);
    }
    if (path === '/robot-voice/renew' || path === '/robot-voice/stop') {
      if (!data.voiceSession || data.voiceSession.voice_session_id !== body.voice_session_id) return jsonResponse({ detail: 'Unknown voice session' }, 404);
      if (path.endsWith('stop')) Object.assign(data.voiceSession, { state: 'stopped', stop_reason: 'Stopped by owner' });
      return jsonResponse(data.voiceSession);
    }
    if (path === '/robot-voice/wake') {
      const robot = data.robots.find((r: any) => r.robot_id === body.robot_id);
      if (robot) robot.wake_armed = body.armed;
      return jsonResponse({ robots: data.robots, session: data.voiceSession });
    }
    m = path.match(/^\/robots\/([^/]+)\/settings\/motion$/);
    if (m) {
      if (method === 'PUT') { data.motionWrites.push(body); Object.assign(data.motion, body); }
      return jsonResponse(data.motion);
    }
    if (path.startsWith('/settings/accounts/google')) {
      const sub = path.slice('/settings/accounts/google'.length);
      data.googleCalls.push({ call: `${method} ${sub || '/'}`, body });
      const g = data.google;
      if (sub === '' && method === 'GET') return jsonResponse(g);
      if (sub === '/configure') { Object.assign(g, { configured: true, client_type: body.client_type }); return jsonResponse(g); }
      if (sub === '/connect') return jsonResponse({ authorization_url: data.authUrl ?? 'https://accounts.google.com/o/oauth2/auth?x=1' });
      if (sub === '/desktop/start') return jsonResponse({ client_id: "id'with'quotes", scope: 'gmail', state: 'st', binding: 'b'.repeat(24), code_challenge: 'cc' });
      if (sub === '/complete') { g.identity = { email: 'me@example.com' }; g.capabilities.calendar = { status: 'connected', enabled: true, last_success: '2030-01-01T00:00:00Z' }; return jsonResponse(g); }
      if (sub === '/test') { g.capabilities[body.capability].status = 'connected'; g.capabilities[body.capability].last_success = '2030-01-02T00:00:00Z'; return jsonResponse(g); }
      if (sub === '/disconnect') { Object.assign(g, { identity: null, scopes: [], selected_calendars: [] }); g.capabilities.gmail.enabled = false; g.capabilities.calendar.enabled = false; return jsonResponse({ status: g, revocation: data.revoked ? 'revoked' : 'failed' }); }
      if (sub === '/calendars') return jsonResponse({ calendars: data.calendars });
      if (sub === '/selection') { g.selected_calendars = body.calendar_ids; return jsonResponse(g); }
      if (sub.startsWith('/events')) return jsonResponse({ events: data.events });
      if (sub.startsWith('/free-busy')) return jsonResponse({ busy: data.busy });
      if (sub === '/messages') return jsonResponse({ messages: data.mail });
      const mm = sub.match(/^\/messages\/(.+)$/);
      if (mm) return jsonResponse(data.mailBodies[decodeURIComponent(mm[1]!)] ?? { body: '', snippet: '' });
      return jsonResponse({ detail: 'Not Found' }, 404);
    }
    if (path === '/providers/credentials') return jsonResponse(data.credentials);
    m = path.match(/^\/providers\/([^/]+)\/credential$/);
    if (m) {
      if (method === 'PUT') {
        data.secrets.push(body.value);
        data.credentials = [...data.credentials.filter((c: any) => c.provider !== m![1]), { provider: m[1], last_four: String(body.value).slice(-4), updated_at: '2030-01-03T00:00:00Z' }];
        data.saves.push({ call: `credential ${m[1]}`, body });
        return jsonResponse({ provider: m[1], last_four: String(body.value).slice(-4) });
      }
      data.credentials = data.credentials.filter((c: any) => c.provider !== m![1]);
      return jsonResponse({ deleted: true });
    }
    m = path.match(/^\/(audit|notifications)\/([^/]+)$/);
    if (m) return jsonResponse(m[1] === 'audit' ? data.audit : data.queued);
    if (path.startsWith('/coding-agents/')) {
      const sub = path.slice('/coding-agents'.length);
      const cd = data.coding;
      if (sub === '/allowance/claude-code') return jsonResponse(cd.allowance);
      if (sub === '/projects' && method === 'GET') return jsonResponse(cd.projects);
      if (sub === '/projects') { cd.projects.push({ id: nextId('p'), ...body }); return jsonResponse(cd.projects.at(-1)); }
      if (sub === '/sessions' && method === 'GET') return jsonResponse(cd.sessions);
      if (sub === '/sessions') { cd.starts.push(body); return jsonResponse({ id: nextId('s'), status: 'starting', started_at: null, last_activity_at: null, last_event: null, ...body }); }
      if (sub === '/terminal-sessions') return jsonResponse(cd.terminal);
      const ss = sub.match(/^\/sessions\/([^/]+)\/(events|usage|refresh|stop)$/);
      if (ss) {
        if (ss[2] === 'events') return jsonResponse(cd.events[ss[1]!] ?? []);
        if (ss[2] === 'usage') return jsonResponse({ dimensions: cd.usage[ss[1]!] ?? [] });
        const sess = cd.sessions.find((x: any) => x.id === ss[1]);
        if (sess && ss[2] === 'stop') sess.status = 'stopped';
        return jsonResponse(sess ?? {});
      }
      return jsonResponse({ detail: 'Not Found' }, 404);
    }
    if (path.startsWith('/owner-recognition')) {
      const rc = data.recognition;
      const sub = path.slice('/owner-recognition'.length);
      data.saves.push({ call: `${method} ${sub}`, body });
      const totals = () => ({ ...rc, voice_total_bytes: rc.voice_samples.reduce((a: number, x: any) => a + x.size_bytes, 0), face_total_bytes: rc.face_samples.reduce((a: number, x: any) => a + x.size_bytes, 0) });
      if (sub === '/status') return jsonResponse(totals());
      if (sub === '/reauth') {
        if (body.password !== 'correct-password') return jsonResponse({ detail: 'Invalid password' }, 401);
        rc.reauthenticated = true; rc.reauth_expires_in_seconds = 300;
        return jsonResponse({ ok: true });
      }
      if (!rc.reauthenticated) return jsonResponse({ detail: 'Confirm your password first' }, 403);
      if (sub === '/benchmark/enabled') { rc.benchmark_enabled = body.enabled; return jsonResponse({ ok: true }); }
      const k = sub.match(/^\/benchmark\/(voice|face)\/(samples|export)(?:\/(.+))?$/);
      if (k) {
        const list = rc[`${k[1]}_samples`];
        if (k[2] === 'export') return new Response('zipbytes', { status: 200, headers: { 'Content-Type': 'application/zip' } });
        if (method === 'POST') {
          if (!rc.benchmark_enabled) return jsonResponse({ detail: 'Benchmark collection is off' }, 403);
          list.push({ sample_id: nextId('smp'), kind: k[1], captured_at: '2030-01-02T03:04:05Z', content_type: body.blob.type, size_bytes: body.blob.size });
          return jsonResponse(list.at(-1));
        }
        if (method === 'DELETE' && k[3]) { rc[`${k[1]}_samples`] = list.filter((x: any) => x.sample_id !== decodeURIComponent(k[3]!)); return jsonResponse({ deleted: true }); }
        if (method === 'DELETE') { rc[`${k[1]}_samples`] = []; return jsonResponse({ deleted: true }); }
      }
      return jsonResponse({ detail: 'Not Found' }, 404);
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
        rawBody instanceof Blob
          ? { blob: { size: rawBody.size, type: rawBody.type } }
          : rawBody instanceof FormData
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
