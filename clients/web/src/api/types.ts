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
  entries: UsageEntry[];
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
      entries: list(data.entries ?? [], 'usage.entries').map((item, i) => {
        const e = obj(item, `usage.entries[${i}]`);
        return {
          at: str(e.at, 'entry.at'),
          role: e.role == null ? '' : str(e.role, 'entry.role'),
          model: e.model == null ? '' : str(e.model, 'entry.model'),
          success: e.success === true,
          error_message: optionalStr(e.error_message, 'entry.error_message'),
          prompt_tokens: optionalNum(e.prompt_tokens, 'entry.prompt_tokens'),
          completion_tokens: optionalNum(e.completion_tokens, 'entry.completion_tokens'),
          latency_ms: e.latency_ms == null ? 0 : num(e.latency_ms, 'entry.latency_ms'),
        };
      }),
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

// --- Meetings (Phase 47B6) -----------------------------------------------------------------

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}
export interface SpeakerSegment {
  start: number;
  end: number;
  speaker: string;
}
export interface MeetingOutput {
  text: string;
  tier: string; // 'local' | 'deep' | 'cloud'
  generated_at: string | null;
}
export interface Meeting {
  id: string;
  title: string;
  description: string | null;
  status: string;
  created_at: string;
  project_scope: string | null;
  participants: string[];
  context: string | null;
  duration_seconds: number | null;
  error_detail: string | null;
  transcript_segments: TranscriptSegment[] | null;
  diarization_segments: SpeakerSegment[] | null;
  aligned_speakers: (string | null)[] | null;
  audio_gaps: { seconds: number; segments: number[] } | null;
  speaker_names: Record<string, string>;
  transcript_corrections: Record<string, string>;
  summary: MeetingOutput | null;
  minutes: MeetingOutput | null;
}

export interface Suggestion {
  original: string;
  suggested: string;
  confidence: string;
  reason: string;
}
export interface SuggestionResult {
  suggestions: Suggestion[];
  terms_used: number;
  truncated: boolean;
}
export interface DeepJob {
  id: string;
  status: string;
  stage: string;
  task: string | null;
  meeting_id: string | null;
  meeting_title: string | null;
  reachy_unavailable: boolean;
  reachy_online: boolean;
  error: string | null;
  result: SuggestionResult | null;
}
export interface DeepInfo {
  available: boolean;
  reason: string | null;
  eta_seconds: number;
}

function optionalNum(value: unknown, what: string): number | null {
  return value == null ? null : num(value, what);
}
function optionalStr(value: unknown, what: string): string | null {
  return value == null ? null : str(value, what);
}
function parseOutput(value: unknown, what: string): MeetingOutput | null {
  if (value == null) return null;
  const o = obj(value, what);
  return { text: str(o.text, `${what}.text`), tier: str(o.tier, `${what}.tier`), generated_at: optionalStr(o.generated_at, `${what}.generated_at`) };
}

export function parseMeeting(value: unknown, what = 'meeting'): Meeting {
  const o = obj(value, what);
  const transcript =
    o.transcript_segments == null
      ? null
      : list(o.transcript_segments, `${what}.transcript_segments`).map((item, i) => {
          const s = obj(item, `${what}.transcript_segments[${i}]`);
          return { start: num(s.start, 'segment.start'), end: num(s.end, 'segment.end'), text: s.text == null ? '' : str(s.text, 'segment.text') };
        });
  const diarization =
    o.diarization_segments == null
      ? null
      : list(o.diarization_segments, `${what}.diarization_segments`).map((item, i) => {
          const s = obj(item, `${what}.diarization_segments[${i}]`);
          return { start: num(s.start, 'segment.start'), end: num(s.end, 'segment.end'), speaker: s.speaker == null ? '' : str(s.speaker, 'segment.speaker') };
        });
  const aligned =
    o.aligned_segments == null
      ? null
      : list(o.aligned_segments, `${what}.aligned_segments`).map((item) => {
          const s = obj(item, 'aligned segment');
          return s.speaker == null ? null : str(s.speaker, 'aligned segment.speaker');
        });
  const gaps = o.audio_gaps == null ? null : obj(o.audio_gaps, `${what}.audio_gaps`);
  const names = o.speaker_names == null ? {} : obj(o.speaker_names, `${what}.speaker_names`);
  const corrections = o.transcript_corrections == null ? {} : obj(o.transcript_corrections, `${what}.transcript_corrections`);
  return {
    id: str(o.id, `${what}.id`),
    title: str(o.title, `${what}.title`),
    description: optionalStr(o.description, `${what}.description`),
    status: str(o.status, `${what}.status`),
    created_at: str(o.created_at, `${what}.created_at`),
    project_scope: optionalStr(o.project_scope, `${what}.project_scope`),
    participants: o.participants == null ? [] : list(o.participants, `${what}.participants`).map((p) => str(p, 'participant')),
    context: optionalStr(o.context, `${what}.context`),
    duration_seconds: optionalNum(o.duration_seconds, `${what}.duration_seconds`),
    error_detail: optionalStr(o.error_detail, `${what}.error_detail`),
    transcript_segments: transcript,
    diarization_segments: diarization,
    aligned_speakers: aligned,
    audio_gaps: gaps
      ? { seconds: gaps.seconds == null ? 0 : num(gaps.seconds, 'audio_gaps.seconds'), segments: gaps.segments == null ? [] : list(gaps.segments, 'audio_gaps.segments').map((n) => num(n, 'gap segment')) }
      : null,
    speaker_names: Object.fromEntries(Object.entries(names).map(([k, v]) => [k, str(v, 'speaker name')])),
    transcript_corrections: Object.fromEntries(Object.entries(corrections).map(([k, v]) => [k, str(v, 'correction')])),
    summary: parseOutput(o.summary, `${what}.summary`),
    minutes: parseOutput(o.minutes, `${what}.minutes`),
  };
}
export const parseMeetings = (value: unknown): Meeting[] => list(value, 'meetings').map((v, i) => parseMeeting(v, `meetings[${i}]`));

export function parseSuggestionResult(value: unknown): SuggestionResult {
  const o = obj(value, 'suggestions');
  return {
    suggestions: list(o.suggestions ?? [], 'suggestions.suggestions').map((item, i) => {
      const s = obj(item, `suggestions[${i}]`);
      return {
        original: str(s.original, 'suggestion.original'),
        suggested: str(s.suggested, 'suggestion.suggested'),
        confidence: s.confidence == null ? '' : str(s.confidence, 'suggestion.confidence'),
        reason: s.reason == null ? '' : str(s.reason, 'suggestion.reason'),
      };
    }),
    terms_used: o.terms_used == null ? 0 : num(o.terms_used, 'suggestions.terms_used'),
    truncated: o.truncated === true,
  };
}

export function parseDeepJob(value: unknown): DeepJob {
  const o = obj(value, 'deep review');
  return {
    id: str(o.id, 'job.id'),
    status: str(o.status, 'job.status'),
    stage: o.stage == null ? '' : str(o.stage, 'job.stage'),
    task: optionalStr(o.task, 'job.task'),
    meeting_id: optionalStr(o.meeting_id, 'job.meeting_id'),
    meeting_title: optionalStr(o.meeting_title, 'job.meeting_title'),
    reachy_unavailable: o.reachy_unavailable === true,
    reachy_online: o.reachy_online !== false,
    error: optionalStr(o.error, 'job.error'),
    result: o.result == null ? null : parseSuggestionResult(o.result),
  };
}

export function parseDeepInfo(value: unknown): DeepInfo {
  const o = obj(value, 'deep review info');
  return {
    available: o.available === true,
    reason: optionalStr(o.reason, 'info.reason'),
    eta_seconds: o.eta_seconds == null ? 330 : num(o.eta_seconds, 'info.eta_seconds'),
  };
}

// --- Settings (Phase 47B7) -----------------------------------------------------------------
// API keys never come back from the hub: a saved key is shown as a masked tail ("********2345") and sent only when changed.

export interface ProviderConfig {
  base_url: string;
  model: string;
  api_key: string | null; // masked
}
export interface LlmConfig {
  local: ProviderConfig | null;
  cloud: ProviderConfig | null;
  routing: string; // 'local_only' | 'local_with_cloud_fallback' | 'cloud_only'
}
export interface Persona {
  name: string;
  system_prompt: string;
  location: string | null;
  timezone: string;
  tone: string;
}
export interface HostedSearch {
  enabled: boolean;
  api_key: string | null; // masked
  monthly_limit: number | null;
}
export interface SearchUsage {
  period: string;
  used: Record<string, number>;
  limits: Record<string, number>;
  enabled: Record<string, boolean>;
}
export interface WebSearchConfig {
  policy: string; // 'off' | 'auto' | 'always'
  hosted: Record<string, HostedSearch>;
  fallback: string; // 'builtin_searxng' | 'searxng' | 'none'
  base_url: string | null;
  api_key: string | null; // masked
  result_count: number;
  usage: SearchUsage | null;
}
export interface SearchLogEntry {
  at: string;
  served_by: string | null;
  total_ms: number;
  policy: string;
  query: string;
  attempts: { provider: string; outcome: string; ms: number }[];
  results: SearchSource[];
}
export interface SearchLog {
  usage: SearchUsage | null;
  entries: SearchLogEntry[];
}

function provider(value: unknown, what: string): ProviderConfig | null {
  if (value == null) return null;
  const o = obj(value, what);
  return { base_url: str(o.base_url, `${what}.base_url`), model: str(o.model, `${what}.model`), api_key: optionalStr(o.api_key, `${what}.api_key`) };
}

export function parseLlmConfig(value: unknown): LlmConfig {
  const o = obj(value, 'llm settings');
  return {
    local: provider(o.local, 'llm.local'),
    cloud: provider(o.cloud, 'llm.cloud'),
    routing: o.routing == null ? 'local_only' : str(obj(o.routing, 'llm.routing').mode, 'llm.routing.mode'),
  };
}

export function parsePersona(value: unknown): Persona {
  const o = obj(value, 'persona');
  return {
    name: str(o.name, 'persona.name'),
    system_prompt: str(o.system_prompt, 'persona.system_prompt'),
    location: optionalStr(o.location, 'persona.location'),
    timezone: o.timezone == null ? 'UTC' : str(o.timezone, 'persona.timezone'),
    tone: o.tone == null ? 'default' : str(o.tone, 'persona.tone'),
  };
}

function numberMap(value: unknown, what: string): Record<string, number> {
  return Object.fromEntries(Object.entries(obj(value ?? {}, what)).map(([k, v]) => [k, num(v, `${what}.${k}`)]));
}
function parseUsage(value: unknown): SearchUsage | null {
  if (value == null) return null;
  const o = obj(value, 'search usage');
  return {
    period: str(o.period, 'usage.period'),
    used: numberMap(o.used, 'usage.used'),
    limits: numberMap(o.limits, 'usage.limits'),
    enabled: Object.fromEntries(Object.entries(obj(o.enabled ?? {}, 'usage.enabled')).map(([k, v]) => [k, v === true])),
  };
}

export function parseWebSearchSettings(value: unknown): WebSearchConfig {
  const o = obj(value, 'web search settings');
  const hosted: Record<string, HostedSearch> = {};
  for (const [name, entry] of Object.entries(obj(o.hosted ?? {}, 'web search.hosted'))) {
    const h = obj(entry, `hosted.${name}`);
    hosted[name] = { enabled: h.enabled === true, api_key: optionalStr(h.api_key, `hosted.${name}.api_key`), monthly_limit: optionalNum(h.monthly_limit, `hosted.${name}.monthly_limit`) };
  }
  return {
    policy: str(o.policy, 'web search.policy'),
    hosted,
    fallback: o.fallback == null ? 'builtin_searxng' : str(o.fallback, 'web search.fallback'),
    base_url: optionalStr(o.base_url, 'web search.base_url'),
    api_key: optionalStr(o.api_key, 'web search.api_key'),
    result_count: o.result_count == null ? 5 : num(o.result_count, 'web search.result_count'),
    usage: parseUsage(o.usage),
  };
}

export function parseSearchLog(value: unknown): SearchLog {
  const o = obj(value ?? {}, 'search log');
  return {
    usage: parseUsage(o.usage),
    entries: list(o.entries ?? [], 'search log.entries').map((item, i) => {
      const e = obj(item, `log[${i}]`);
      return {
        at: str(e.at, 'log.at'),
        served_by: optionalStr(e.served_by, 'log.served_by'),
        total_ms: e.total_ms == null ? 0 : num(e.total_ms, 'log.total_ms'),
        policy: e.policy == null ? '' : str(e.policy, 'log.policy'),
        query: str(e.query, 'log.query'),
        attempts: list(e.attempts ?? [], 'log.attempts').map((a) => {
          const at = obj(a, 'attempt');
          return { provider: str(at.provider, 'attempt.provider'), outcome: str(at.outcome, 'attempt.outcome'), ms: at.ms == null ? 0 : num(at.ms, 'attempt.ms') };
        }),
        results: list(e.results ?? [], 'log.results').map((r) => {
          const x = obj(r, 'result');
          const text = (key: string) => (x[key] == null ? '' : str(x[key], `result.${key}`));
          return { title: text('title'), url: text('url'), snippet: text('snippet'), source_domain: text('source_domain') };
        }),
      };
    }),
  };
}

export interface UsageEntry {
  at: string;
  role: string;
  model: string;
  success: boolean;
  error_message: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  latency_ms: number;
}

// --- Voice and robot settings (Phase 47B8) --------------------------------------------------

export interface VoiceTurn {
  turn: number;
  transcript: string;
  outcome: string; // 'spoken' | 'withheld' | 'no_speech' | 'failed' | 'cancelled' | ...
  reply: string;
  reason: string;
  web_search: WebSearch | null;
}
export interface VoiceSession {
  voice_session_id: string;
  state: string; // 'starting' | 'listening' | 'thinking' | 'speaking' | 'stopped'
  stop_reason: string | null;
  last_error: string | null;
  wake_started: boolean;
  turns: VoiceTurn[];
}
export interface VoiceRobot {
  robot_id: string;
  online: boolean;
  voice_capable: boolean;
  wake_capable: boolean;
  wake_armed: boolean;
  wake_counts: { candidates: number; admitted: number };
}
export interface VoiceOverview {
  robots: VoiceRobot[];
  session: VoiceSession | null;
}
export interface MotionSettings {
  conversation_motion: boolean;
  speech_wobble: boolean;
  conversation_active: boolean;
}
export interface RobotRef {
  robot_id: string;
}

export function parseVoiceSession(value: unknown, what = 'voice session'): VoiceSession {
  const o = obj(value, what);
  return {
    voice_session_id: str(o.voice_session_id, `${what}.voice_session_id`),
    state: str(o.state, `${what}.state`),
    stop_reason: optionalStr(o.stop_reason, `${what}.stop_reason`),
    last_error: optionalStr(o.last_error, `${what}.last_error`),
    wake_started: o.wake_started === true,
    turns: list(o.turns ?? [], `${what}.turns`).map((item, i) => {
      const t = obj(item, `${what}.turns[${i}]`);
      return {
        turn: num(t.turn, 'turn.turn'),
        transcript: t.transcript == null ? '' : str(t.transcript, 'turn.transcript'),
        outcome: str(t.outcome, 'turn.outcome'),
        reply: t.reply == null ? '' : str(t.reply, 'turn.reply'),
        reason: t.reason == null ? '' : str(t.reason, 'turn.reason'),
        web_search: parseWebSearch(t.web_search, 'turn.web_search'),
      };
    }),
  };
}

export function parseVoiceOverview(value: unknown): VoiceOverview {
  const o = obj(value, 'robot voice');
  return {
    robots: list(o.robots ?? [], 'robot voice.robots').map((item, i) => {
      const r = obj(item, `robots[${i}]`);
      const counts = r.wake_counts == null ? {} : obj(r.wake_counts, 'wake_counts');
      return {
        robot_id: str(r.robot_id, 'robot.robot_id'),
        online: r.online === true,
        voice_capable: r.voice_capable === true,
        wake_capable: r.wake_capable === true,
        wake_armed: r.wake_armed === true,
        wake_counts: { candidates: typeof counts.candidates === 'number' ? counts.candidates : 0, admitted: typeof counts.admitted === 'number' ? counts.admitted : 0 },
      };
    }),
    session: o.session == null ? null : parseVoiceSession(o.session),
  };
}

export function parseMotion(value: unknown): MotionSettings {
  const o = obj(value, 'motion settings');
  // A robot that does not support animation settings answers with something else; refuse to show it as editable.
  if (typeof o.conversation_motion !== 'boolean' || typeof o.speech_wobble !== 'boolean' || typeof o.conversation_active !== 'boolean') {
    throw new ApiShapeError('This robot does not support animation settings.');
  }
  return { conversation_motion: o.conversation_motion, speech_wobble: o.speech_wobble, conversation_active: o.conversation_active };
}

export const parseRobotRefs = (value: unknown): RobotRef[] =>
  list(value, 'robots').map((item, i) => ({ robot_id: str(obj(item, `robots[${i}]`).robot_id, 'robot.robot_id') }));

// --- Connected accounts and coding-agent credentials (Phase 47B9) -----------------------------

export interface CapabilityState {
  status: string;
  enabled: boolean;
  last_success: string | null;
}
export interface GoogleStatus {
  configured: boolean;
  client_type: string | null;
  identity: { email: string } | null;
  capabilities: { gmail: CapabilityState; calendar: CapabilityState };
  scopes: string[];
  selected_calendars: string[];
}
export interface CalendarInfo {
  id: string;
  name: string;
  timezone: string;
}
export interface CalendarEvent {
  title: string;
  all_day: boolean;
  start: string;
}
export interface MailMessage {
  id: string;
  sender: string;
  subject: string;
}
export interface DesktopStart {
  client_id: string;
  scope: string;
  state: string;
  binding: string;
  code_challenge: string;
}
export interface CredentialRecord {
  provider: string;
  last_four: string;
  updated_at: string;
}

function capability(value: unknown, what: string): CapabilityState {
  const o = obj(value, what);
  return { status: str(o.status, `${what}.status`), enabled: o.enabled === true, last_success: optionalStr(o.last_success, `${what}.last_success`) };
}

export function parseGoogleStatus(value: unknown): GoogleStatus {
  const o = obj(value, 'google status');
  const caps = obj(o.capabilities, 'google.capabilities');
  return {
    configured: o.configured === true,
    client_type: optionalStr(o.client_type, 'google.client_type'),
    identity: o.identity == null ? null : { email: str(obj(o.identity, 'google.identity').email, 'google.identity.email') },
    capabilities: { gmail: capability(caps.gmail, 'capabilities.gmail'), calendar: capability(caps.calendar, 'capabilities.calendar') },
    scopes: list(o.scopes ?? [], 'google.scopes').map((s) => str(s, 'scope')),
    selected_calendars: list(o.selected_calendars ?? [], 'google.selected_calendars').map((s) => str(s, 'calendar id')),
  };
}

export const parseCalendars = (value: unknown): CalendarInfo[] =>
  list(obj(value, 'calendars').calendars, 'calendars.calendars').map((item, i) => {
    const c = obj(item, `calendars[${i}]`);
    return { id: str(c.id, 'calendar.id'), name: str(c.name, 'calendar.name'), timezone: c.timezone == null ? '' : str(c.timezone, 'calendar.timezone') };
  });

export const parseEvents = (value: unknown): CalendarEvent[] =>
  list(obj(value, 'events').events, 'events.events').map((item, i) => {
    const e = obj(item, `events[${i}]`);
    return { title: str(e.title, 'event.title'), all_day: e.all_day === true, start: str(e.start, 'event.start') };
  });

export const parseBusy = (value: unknown): { start: string; end: string }[] =>
  list(obj(value, 'free-busy').busy, 'free-busy.busy').map((item, i) => {
    const b = obj(item, `busy[${i}]`);
    return { start: str(b.start, 'busy.start'), end: str(b.end, 'busy.end') };
  });

export const parseMessages = (value: unknown): MailMessage[] =>
  list(obj(value, 'messages').messages, 'messages.messages').map((item, i) => {
    const m = obj(item, `messages[${i}]`);
    return { id: str(m.id, 'message.id'), sender: m.sender == null ? '' : str(m.sender, 'message.sender'), subject: m.subject == null ? '' : str(m.subject, 'message.subject') };
  });

export const parseMessageBody = (value: unknown): string => {
  const o = obj(value, 'message');
  return o.body ? str(o.body, 'message.body') : o.snippet == null ? '' : str(o.snippet, 'message.snippet');
};

export function parseDesktopStart(value: unknown): DesktopStart {
  const o = obj(value, 'desktop start');
  return {
    client_id: str(o.client_id, 'desktop.client_id'),
    scope: str(o.scope, 'desktop.scope'),
    state: str(o.state, 'desktop.state'),
    binding: str(o.binding, 'desktop.binding'),
    code_challenge: str(o.code_challenge, 'desktop.code_challenge'),
  };
}

export const parseCredentials = (value: unknown): CredentialRecord[] =>
  list(value, 'credentials').map((item, i) => {
    const c = obj(item, `credentials[${i}]`);
    return { provider: str(c.provider, 'credential.provider'), last_four: str(c.last_four, 'credential.last_four'), updated_at: str(c.updated_at, 'credential.updated_at') };
  });

// --- Owner recognition benchmark dataset (Phase 47B10) --------------------------------------

export interface RecognitionSample {
  sample_id: string;
  captured_at: string;
  size_bytes: number;
}
export interface RecognitionStatus {
  benchmark_enabled: boolean;
  reauthenticated: boolean;
  reauth_expires_in_seconds: number;
  voice_samples: RecognitionSample[];
  face_samples: RecognitionSample[];
  voice_total_bytes: number;
  face_total_bytes: number;
}

function samples(value: unknown, what: string): RecognitionSample[] {
  return list(value ?? [], what).map((item, i) => {
    const s = obj(item, `${what}[${i}]`);
    return { sample_id: str(s.sample_id, 'sample.sample_id'), captured_at: str(s.captured_at, 'sample.captured_at'), size_bytes: num(s.size_bytes, 'sample.size_bytes') };
  });
}

export function parseRecognitionStatus(value: unknown): RecognitionStatus {
  const o = obj(value, 'recognition status');
  return {
    benchmark_enabled: o.benchmark_enabled === true,
    reauthenticated: o.reauthenticated === true,
    reauth_expires_in_seconds: typeof o.reauth_expires_in_seconds === 'number' ? o.reauth_expires_in_seconds : 0,
    voice_samples: samples(o.voice_samples, 'voice_samples'),
    face_samples: samples(o.face_samples, 'face_samples'),
    voice_total_bytes: typeof o.voice_total_bytes === 'number' ? o.voice_total_bytes : 0,
    face_total_bytes: typeof o.face_total_bytes === 'number' ? o.face_total_bytes : 0,
  };
}

// --- Coding agents (Phase 47B11) ----------------------------------------------------------

export interface Dimension {
  name: string;
  value: number | string;
  unit: string;
  resets_at: string | null;
}
export interface Allowance {
  source: string;
  windows: Dimension[];
}
export interface CodingProject {
  id: string;
  name: string;
  repository_path: string;
  default_branch: string;
  provider: string;
}
export interface CodingSession {
  id: string;
  project_id: string;
  status: string;
  task_summary: string;
  started_at: string | null;
  last_activity_at: string | null;
  branch: string | null;
  last_event: string | null;
}
export interface CodingEvent {
  timestamp: string | null;
  type: string;
  summary: string;
}
export interface TerminalSession {
  session_id: string;
  title: string | null;
  active: boolean;
  project_path: string | null;
  git_branch: string | null;
  last_activity_at: string | null;
  last_prompt: string | null;
}

function dimensions(value: unknown, what: string): Dimension[] {
  return list(value ?? [], what).map((item, i) => {
    const d = obj(item, `${what}[${i}]`);
    return {
      name: str(d.name, 'dimension.name'),
      value: typeof d.value === 'number' ? d.value : str(d.value, 'dimension.value'),
      unit: d.unit == null ? '' : str(d.unit, 'dimension.unit'),
      resets_at: optionalStr(d.resets_at, 'dimension.resets_at'),
    };
  });
}

export function parseAllowance(value: unknown): Allowance {
  const o = obj(value, 'allowance');
  return { source: o.source == null ? '' : str(o.source, 'allowance.source'), windows: dimensions(o.windows, 'allowance.windows') };
}
export const parseUsageDimensions = (value: unknown): Dimension[] => dimensions(obj(value, 'usage').dimensions, 'usage.dimensions');

export const parseCodingProjects = (value: unknown): CodingProject[] =>
  list(value, 'projects').map((item, i) => {
    const p = obj(item, `projects[${i}]`);
    return {
      id: str(p.id, 'project.id'),
      name: str(p.name, 'project.name'),
      repository_path: str(p.repository_path, 'project.repository_path'),
      default_branch: p.default_branch == null ? 'main' : str(p.default_branch, 'project.default_branch'),
      provider: p.provider == null ? '' : str(p.provider, 'project.provider'),
    };
  });

export const parseCodingSessions = (value: unknown): CodingSession[] =>
  list(value, 'sessions').map((item, i) => {
    const s = obj(item, `sessions[${i}]`);
    return {
      id: str(s.id, 'session.id'),
      project_id: str(s.project_id, 'session.project_id'),
      status: str(s.status, 'session.status'),
      task_summary: s.task_summary == null ? '' : str(s.task_summary, 'session.task_summary'),
      started_at: optionalStr(s.started_at, 'session.started_at'),
      last_activity_at: optionalStr(s.last_activity_at, 'session.last_activity_at'),
      branch: optionalStr(s.branch, 'session.branch'),
      last_event: optionalStr(s.last_event, 'session.last_event'),
    };
  });

export const parseCodingEvents = (value: unknown): CodingEvent[] =>
  list(value, 'events').map((item, i) => {
    const e = obj(item, `events[${i}]`);
    return { timestamp: optionalStr(e.timestamp, 'event.timestamp'), type: str(e.type, 'event.type'), summary: e.summary == null ? '' : str(e.summary, 'event.summary') };
  });

export const parseTerminalSessions = (value: unknown): TerminalSession[] =>
  list(value, 'terminal sessions').map((item, i) => {
    const s = obj(item, `terminal[${i}]`);
    return {
      session_id: str(s.session_id, 'terminal.session_id'),
      title: optionalStr(s.title, 'terminal.title'),
      active: s.active === true,
      project_path: optionalStr(s.project_path, 'terminal.project_path'),
      git_branch: optionalStr(s.git_branch, 'terminal.git_branch'),
      last_activity_at: optionalStr(s.last_activity_at, 'terminal.last_activity_at'),
      last_prompt: optionalStr(s.last_prompt, 'terminal.last_prompt'),
    };
  });

export interface AuditEntry {
  action: string | null;
  reason: string | null;
  delivery_channel: string | null;
}
export interface QueuedNotification {
  text: string | null;
  reason: string | null;
}
export const parseAudit = (value: unknown): AuditEntry[] =>
  list(value, 'audit').map((item, i) => {
    const e = obj(item, `audit[${i}]`);
    return { action: optionalStr(e.action, 'audit.action'), reason: optionalStr(e.reason, 'audit.reason'), delivery_channel: optionalStr(e.delivery_channel, 'audit.delivery_channel') };
  });
export const parseNotifications = (value: unknown): QueuedNotification[] =>
  list(value, 'notifications').map((item, i) => {
    const e = obj(item, `notifications[${i}]`);
    return { text: optionalStr(e.text, 'notification.text'), reason: optionalStr(e.reason, 'notification.reason') };
  });

// --- Brain (Phase 47D) ----------------------------------------------------------------------

export interface BrainNodeDto {
  id: string;
  type: string;
  title: string;
  excerpt: string;
  observed_at: string | null;
  source_ref: { kind: string; id: string };
  sensitivity: string;
  project_scope: string | null;
}
export interface BrainPageDto {
  nodes: BrainNodeDto[];
  next: string | null;
  truncated: boolean;
}
export interface BrainSummaryDto {
  total: number;
  by_type: Record<string, number>;
  edges: number;
  truncated: boolean;
}
export interface BrainEdgesDto {
  edges: { id: string; from: string; to: string; basis: string }[];
  note: string;
}

export function parseBrainNode(value: unknown, what = 'brain node'): BrainNodeDto {
  const o = obj(value, what);
  const ref = obj(o.source_ref, `${what}.source_ref`);
  return {
    id: str(o.id, `${what}.id`),
    type: str(o.type, `${what}.type`),
    title: str(o.title, `${what}.title`),
    excerpt: o.excerpt == null ? '' : str(o.excerpt, `${what}.excerpt`),
    observed_at: optionalStr(o.observed_at, `${what}.observed_at`),
    source_ref: { kind: str(ref.kind, 'source_ref.kind'), id: str(ref.id, 'source_ref.id') },
    sensitivity: o.sensitivity == null ? '' : str(o.sensitivity, `${what}.sensitivity`),
    project_scope: optionalStr(o.project_scope, `${what}.project_scope`),
  };
}
export function parseBrainPage(value: unknown): BrainPageDto {
  const o = obj(value, 'brain page');
  return {
    nodes: list(o.nodes, 'brain page.nodes').map((n, i) => parseBrainNode(n, `nodes[${i}]`)),
    next: optionalStr(o.next, 'brain page.next'),
    truncated: o.truncated === true,
  };
}
export function parseBrainSummary(value: unknown): BrainSummaryDto {
  const o = obj(value, 'brain summary');
  return {
    total: num(o.total, 'summary.total'),
    by_type: Object.fromEntries(Object.entries(obj(o.by_type, 'summary.by_type')).map(([k, v]) => [k, num(v, `summary.by_type.${k}`)])),
    edges: num(o.edges, 'summary.edges'),
    truncated: o.truncated === true,
  };
}
export function parseBrainEdges(value: unknown): BrainEdgesDto {
  const o = obj(value, 'brain edges');
  return {
    edges: list(o.edges ?? [], 'edges.edges').map((item, i) => {
      const e = obj(item, `edges[${i}]`);
      return { id: str(e.id, 'edge.id'), from: str(e.from, 'edge.from'), to: str(e.to, 'edge.to'), basis: e.basis == null ? '' : str(e.basis, 'edge.basis') };
    }),
    note: o.note == null ? '' : str(o.note, 'edges.note'),
  };
}
