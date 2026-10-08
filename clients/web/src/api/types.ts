// Hand-written because the hub's operator routes return bare dicts, so its
// OpenAPI document has no field-level schema for them. The parsers below check
// exactly the fields the client reads; api/samples.json (a real hub response)
// is run through them in tests, and services/reachy-hub/tests/test_web_client.py
// fails if the hub's responses stop matching that sample.
import { ApiShapeError } from './client';

export type Probe<T> = { status: 'ok'; data: T } | { status: 'unavailable' };

export interface UsageCounts {
  calls: number;
  errors: number;
  prompt_tokens: number;
  completion_tokens: number;
  avg_latency_ms: number;
  unreported_token_calls: number;
}

export interface LlmUsage {
  summary: UsageCounts;
  by_role: Partial<Record<'local' | 'cloud', UsageCounts>>;
  latest_escalation: { reason: string; at: string } | null;
}

export interface TelegramHealth {
  configured: boolean;
  healthy: boolean;
  last_poll_at: string | null;
  last_poll_error: string | null;
}

export interface RobotStatus {
  robot_id: string;
  status: 'ok' | 'unavailable';
  embodiment_state: string | null;
}

export interface HubStatus {
  hubOk: true;
  core: 'ok' | 'unavailable';
  llm: { configured: boolean | null; usage: LlmUsage | null };
  telegram: TelegramHealth;
  robots: RobotStatus[];
  ownerBound: boolean;
  defaultUserId: string | null;
}

type Obj = Record<string, unknown>;

function obj(value: unknown, what: string): Obj {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new ApiShapeError(what);
  return value as Obj;
}
function num(value: unknown, what: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new ApiShapeError(what);
  return value;
}
function str(value: unknown, what: string): string {
  if (typeof value !== 'string') throw new ApiShapeError(what);
  return value;
}
function bool(value: unknown, what: string): boolean {
  if (typeof value !== 'boolean') throw new ApiShapeError(what);
  return value;
}
function okOrUnavailable(value: unknown, what: string): 'ok' | 'unavailable' {
  const status = str(obj(value, what).status, `${what}.status`);
  if (status !== 'ok' && status !== 'unavailable') throw new ApiShapeError(`${what}.status`);
  return status;
}

function counts(value: unknown, what: string): UsageCounts {
  const o = obj(value, what);
  return {
    calls: num(o.calls, `${what}.calls`),
    errors: num(o.errors, `${what}.errors`),
    prompt_tokens: num(o.prompt_tokens, `${what}.prompt_tokens`),
    completion_tokens: num(o.completion_tokens, `${what}.completion_tokens`),
    avg_latency_ms: num(o.avg_latency_ms, `${what}.avg_latency_ms`),
    unreported_token_calls: num(o.unreported_token_calls, `${what}.unreported_token_calls`),
  };
}

export function parseUser(value: unknown): { username: string } {
  return { username: str(obj(value, 'auth/me').username, 'auth/me.username') };
}

export function parseStatus(value: unknown): HubStatus {
  const root = obj(value, 'status');
  const llm = obj(root.llm, 'status.llm');
  const usageProbe = obj(llm.usage, 'status.llm.usage');
  let usage: LlmUsage | null = null;
  if (okOrUnavailable(usageProbe, 'status.llm.usage') === 'ok') {
    const data = obj(usageProbe.data, 'status.llm.usage.data');
    const byRole = obj(data.by_role, 'status.llm.usage.data.by_role');
    const escalation = data.latest_escalation;
    usage = {
      summary: counts(data.summary, 'usage.summary'),
      by_role: {
        ...(byRole.local === undefined ? {} : { local: counts(byRole.local, 'usage.by_role.local') }),
        ...(byRole.cloud === undefined ? {} : { cloud: counts(byRole.cloud, 'usage.by_role.cloud') }),
      },
      latest_escalation:
        escalation == null
          ? null
          : {
              reason: str(obj(escalation, 'escalation').reason, 'escalation.reason'),
              at: str(obj(escalation, 'escalation').at, 'escalation.at'),
            },
    };
  }
  const telegram = obj(root.telegram, 'status.telegram');
  if (!Array.isArray(root.robots)) throw new ApiShapeError('status.robots');
  return {
    hubOk: true,
    core: okOrUnavailable(root.companion_core, 'status.companion_core'),
    llm: {
      configured: llm.configured === null ? null : bool(llm.configured, 'status.llm.configured'),
      usage,
    },
    telegram: {
      configured: bool(telegram.configured, 'telegram.configured'),
      healthy: bool(telegram.healthy, 'telegram.healthy'),
      last_poll_at: telegram.last_poll_at == null ? null : str(telegram.last_poll_at, 'telegram.last_poll_at'),
      last_poll_error:
        telegram.last_poll_error == null ? null : str(telegram.last_poll_error, 'telegram.last_poll_error'),
    },
    ownerBound: root.owner_bound === true,
    defaultUserId: typeof root.default_user_id === 'string' ? root.default_user_id : null,
    robots: root.robots.map((item, i) => {
      const robot = obj(item, `status.robots[${i}]`);
      const data = robot.data === undefined ? null : obj(robot.data, `status.robots[${i}].data`);
      const state = data?.embodiment_state;
      return {
        robot_id: str(robot.robot_id, `status.robots[${i}].robot_id`),
        status: okOrUnavailable(robot, `status.robots[${i}]`),
        embodiment_state: typeof state === 'string' ? state : null,
      };
    }),
  };
}

// --- Planner (Phase 47B) ---------------------------------------------------------------
// Tasks, reminders, notes and receipts come back from the hub as bare dicts, like /status.
// Status strings are kept as the hub sends them; the views filter on the values they know,
// as the legacy UI does, so a status the client has not heard of hides a record rather than
// failing the whole list.

export interface Task {
  id: string;
  text: string;
  status: string; // 'open' | 'done'
}

export interface Reminder {
  id: string;
  text: string;
  due_at: string; // an ISO instant in whatever offset the hub echoes; always parse as a Date
  status: string; // 'pending' | 'done'
}

export interface Note {
  id: string;
  title: string;
  body: string;
  updated_at: string;
}

export interface Receipt {
  id: string;
  action_type: string;
  status: string; // 'success' | 'failed'
  at: string;
  source_channel: string;
  fields: Record<string, string>;
  failure_reason: string | null;
}

function list(value: unknown, what: string): unknown[] {
  if (!Array.isArray(value)) throw new ApiShapeError(what);
  return value;
}

export function parseTask(value: unknown, what = 'task'): Task {
  const o = obj(value, what);
  return { id: str(o.id, `${what}.id`), text: str(o.text, `${what}.text`), status: str(o.status, `${what}.status`) };
}
export const parseTasks = (value: unknown): Task[] => list(value, 'tasks').map((v, i) => parseTask(v, `tasks[${i}]`));

export function parseReminder(value: unknown, what = 'reminder'): Reminder {
  const o = obj(value, what);
  const due_at = str(o.due_at, `${what}.due_at`);
  if (Number.isNaN(new Date(due_at).getTime())) throw new ApiShapeError(`${what}.due_at`);
  return { id: str(o.id, `${what}.id`), text: str(o.text, `${what}.text`), due_at, status: str(o.status, `${what}.status`) };
}
export const parseReminders = (value: unknown): Reminder[] =>
  list(value, 'reminders').map((v, i) => parseReminder(v, `reminders[${i}]`));

export function parseNote(value: unknown, what = 'note'): Note {
  const o = obj(value, what);
  const updated_at = str(o.updated_at, `${what}.updated_at`);
  if (Number.isNaN(new Date(updated_at).getTime())) throw new ApiShapeError(`${what}.updated_at`);
  return {
    id: str(o.id, `${what}.id`),
    title: str(o.title, `${what}.title`),
    body: o.body == null ? '' : str(o.body, `${what}.body`),
    updated_at,
  };
}
export const parseNotes = (value: unknown): Note[] => list(value, 'notes').map((v, i) => parseNote(v, `notes[${i}]`));

export function parseReceipts(value: unknown): Receipt[] {
  return list(value, 'receipts').map((item, i) => {
    const o = obj(item, `receipts[${i}]`);
    const rawFields = o.fields == null ? {} : obj(o.fields, `receipts[${i}].fields`);
    const fields: Record<string, string> = {};
    for (const [key, v] of Object.entries(rawFields)) fields[key] = String(v);
    return {
      id: str(o.id, `receipts[${i}].id`),
      action_type: str(o.action_type, `receipts[${i}].action_type`),
      status: str(o.status, `receipts[${i}].status`),
      at: str(o.at, `receipts[${i}].at`),
      source_channel: str(o.source_channel, `receipts[${i}].source_channel`),
      fields,
      failure_reason: o.failure_reason == null ? null : str(o.failure_reason, `receipts[${i}].failure_reason`),
    };
  });
}

// --- Alarms and stations (Phase 47B4) ------------------------------------------------------

export interface Alarm {
  id: string;
  label: string;
  due_at: string;
  station_id: string | null;
  status: string; // 'scheduled' | 'fired' | 'cancelled'
  volume: number;
  repeat: number[]; // 0 = Monday, as the server counts
  enabled: boolean;
  delivery: string | null;
}

export interface Station {
  id: string;
  name: string;
  guide_id: string;
}

export interface StationHit {
  guide_id: string;
  name: string;
  detail: string;
}

export function parseAlarm(value: unknown, what = 'alarm'): Alarm {
  const o = obj(value, what);
  const due_at = str(o.due_at, `${what}.due_at`);
  if (Number.isNaN(new Date(due_at).getTime())) throw new ApiShapeError(`${what}.due_at`);
  const repeat = o.repeat == null ? [] : list(o.repeat, `${what}.repeat`).map((d) => num(d, `${what}.repeat[]`));
  return {
    id: str(o.id, `${what}.id`),
    label: str(o.label, `${what}.label`),
    due_at,
    station_id: o.station_id == null ? null : str(o.station_id, `${what}.station_id`),
    status: str(o.status, `${what}.status`),
    volume: o.volume == null ? 100 : num(o.volume, `${what}.volume`),
    repeat,
    enabled: o.enabled == null ? true : bool(o.enabled, `${what}.enabled`),
    delivery: o.delivery == null ? null : str(o.delivery, `${what}.delivery`),
  };
}
export const parseAlarms = (value: unknown): Alarm[] => list(value, 'alarms').map((v, i) => parseAlarm(v, `alarms[${i}]`));

export function parseStations(value: unknown): Station[] {
  return list(value, 'stations').map((item, i) => {
    const o = obj(item, `stations[${i}]`);
    return { id: str(o.id, `stations[${i}].id`), name: str(o.name, `stations[${i}].name`), guide_id: str(o.guide_id, `stations[${i}].guide_id`) };
  });
}

export function parseStationHits(value: unknown): StationHit[] {
  return list(value, 'stations/search').map((item, i) => {
    const o = obj(item, `stations/search[${i}]`);
    return {
      guide_id: str(o.guide_id, `stations/search[${i}].guide_id`),
      name: str(o.name, `stations/search[${i}].name`),
      detail: o.detail == null ? '' : str(o.detail, `stations/search[${i}].detail`),
    };
  });
}

// --- Chat (Phase 47B5) ---------------------------------------------------------------------

export interface SearchSource {
  title: string;
  url: string;
  snippet: string;
  source_domain: string;
}

export interface WebSearch {
  query: string;
  failed: boolean;
  results: SearchSource[];
}

export interface ChatRecord {
  id: string;
  user_id: string;
  title: string;
  updated_at: string;
}

export interface ChatTurn {
  id: string;
  text: string;
  reply: string | null;
  status: string; // 'pending' | 'complete' | 'unknown'
  web_search: WebSearch | null;
}

export interface ChatDetail extends ChatRecord {
  turns: ChatTurn[];
}

export interface MessageResult {
  reply: string;
  web_search: WebSearch | null;
  context_meeting: string | null;
}

export interface SessionInfo {
  interaction_mode: string;
  dnd: boolean;
  active_channel: string;
}

function parseWebSearch(value: unknown, what: string): WebSearch | null {
  if (value == null) return null;
  const o = obj(value, what);
  return {
    query: str(o.query, `${what}.query`),
    failed: o.failed == null ? false : bool(o.failed, `${what}.failed`),
    results: list(o.results ?? [], `${what}.results`).map((item, i) => {
      const r = obj(item, `${what}.results[${i}]`);
      const text = (key: string) => (r[key] == null ? '' : str(r[key], `${what}.results[${i}].${key}`));
      return { title: text('title'), url: text('url'), snippet: text('snippet'), source_domain: text('source_domain') };
    }),
  };
}

export function parseChatRecord(value: unknown, what = 'chat'): ChatRecord {
  const o = obj(value, what);
  return {
    id: str(o.id, `${what}.id`),
    user_id: str(o.user_id, `${what}.user_id`),
    title: str(o.title, `${what}.title`),
    updated_at: str(o.updated_at, `${what}.updated_at`),
  };
}
export const parseChatRecords = (value: unknown): ChatRecord[] => list(value, 'chats').map((v, i) => parseChatRecord(v, `chats[${i}]`));

export function parseChatDetail(value: unknown): ChatDetail {
  const o = obj(value, 'chat');
  return {
    ...parseChatRecord(value),
    turns: list(o.turns, 'chat.turns').map((item, i) => {
      const t = obj(item, `chat.turns[${i}]`);
      return {
        id: str(t.id, `chat.turns[${i}].id`),
        text: str(t.text, `chat.turns[${i}].text`),
        reply: t.reply == null ? null : str(t.reply, `chat.turns[${i}].reply`),
        status: str(t.status, `chat.turns[${i}].status`),
        web_search: parseWebSearch(t.web_search, `chat.turns[${i}].web_search`),
      };
    }),
  };
}

export function parseMessageResult(value: unknown): MessageResult {
  const o = obj(value, 'message');
  return {
    reply: str(o.reply, 'message.reply'),
    web_search: parseWebSearch(o.web_search, 'message.web_search'),
    context_meeting: o.context_meeting == null ? null : str(o.context_meeting, 'message.context_meeting'),
  };
}

export function parseSession(value: unknown): SessionInfo {
  const o = obj(value, 'session');
  return {
    interaction_mode: str(o.interaction_mode, 'session.interaction_mode'),
    dnd: bool(o.dnd, 'session.dnd'),
    active_channel: str(o.active_channel, 'session.active_channel'),
  };
}
