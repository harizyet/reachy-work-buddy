import { ApiError, ApiShapeError, request } from './client';

// Meeting analysis (Phase 31). The owner asks Reachy to analyse a finished meeting; Reachy lists decisions, open questions and action candidates, each with the transcript
// segment and timestamp it rests on. An action becomes a task only when the owner confirms it here. The hub serves these routes to the signed-in owner only and the server
// decides everything, so this file only shapes requests and checks responses.

export type AnalysisState = 'not_analysed' | 'queued' | 'processing' | 'review_required' | 'completed' | 'failed';
export type ItemKind = 'decision' | 'open_question' | 'action';
export type ItemStatus = 'pending' | 'accepting' | 'accepted' | 'dismissed' | 'noted';

export interface EvidenceDto {
  segment: number;
  start: number;
  end: number;
  speaker: string | null;
  quote: string;
  in_gap: boolean;
}
export type Support = 'stated' | 'uncertain';

export interface ItemDto {
  id: string;
  meeting_id: string;
  kind: ItemKind;
  status: ItemStatus;
  text: string;
  evidence: EvidenceDto[];
  assignee: string | null;
  stated_time: string | null;
  ambiguity: string[];
  support: Support;
  source_changed: boolean;
  task_text: string | null;
  record_id: string | null;
  edited: boolean;
}
export interface RunDto {
  id: string;
  status: 'queued' | 'processing' | 'succeeded' | 'failed';
  error: string | null;
  model: string | null;
  item_count: number;
  rejected: Record<string, number>;
  transcript_hash: string;
}
export interface AnalysisDto {
  meeting_id: string;
  state: AnalysisState;
  run: RunDto | null;
  transcript_changed_since_run: boolean;
  items: ItemDto[];
  created?: boolean;
}

const STATES: readonly string[] = ['not_analysed', 'queued', 'processing', 'review_required', 'completed', 'failed'];
const KINDS: readonly string[] = ['decision', 'open_question', 'action'];
const STATUSES: readonly string[] = ['pending', 'accepting', 'accepted', 'dismissed', 'noted'];
const rec = (v: unknown, what: string): Record<string, unknown> => {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new ApiShapeError(what);
  return v as Record<string, unknown>;
};
const str = (v: unknown, what: string): string => {
  if (typeof v !== 'string') throw new ApiShapeError(what);
  return v;
};
const num = (v: unknown, what: string): number => {
  if (typeof v !== 'number' || !Number.isFinite(v)) throw new ApiShapeError(what);
  return v;
};
const opt = (v: unknown, what: string): string | null => (v == null ? null : str(v, what));
const one = <T extends string>(v: unknown, allowed: readonly string[], what: string): T => {
  if (typeof v !== 'string' || !allowed.includes(v)) throw new ApiShapeError(what);
  return v as T;
};
const arr = (v: unknown, what: string): unknown[] => {
  if (!Array.isArray(v)) throw new ApiShapeError(what);
  return v;
};

export function parseItem(value: unknown): ItemDto {
  const i = rec(value, 'item');
  return {
    id: str(i.id, 'item.id'),
    meeting_id: str(i.meeting_id, 'item.meeting_id'),
    kind: one<ItemKind>(i.kind, KINDS, 'item.kind'),
    status: one<ItemStatus>(i.status, STATUSES, 'item.status'),
    text: str(i.text, 'item.text'),
    evidence: arr(i.evidence, 'item.evidence').map((e) => {
      const x = rec(e, 'item.evidence[]');
      return { segment: num(x.segment, 'evidence.segment'), start: num(x.start, 'evidence.start'), end: num(x.end, 'evidence.end'), speaker: opt(x.speaker, 'evidence.speaker'), quote: str(x.quote, 'evidence.quote'), in_gap: x.in_gap === true };
    }),
    assignee: opt(i.assignee, 'item.assignee'),
    stated_time: opt(i.stated_time, 'item.stated_time'),
    ambiguity: arr(i.ambiguity, 'item.ambiguity').map((a) => str(a, 'item.ambiguity[]')),
    support: one<Support>(i.support, ['stated', 'uncertain'], 'item.support'),
    source_changed: i.source_changed === true,
    task_text: opt(i.task_text, 'item.task_text'),
    record_id: opt(i.record_id, 'item.record_id'),
    edited: i.edited === true,
  };
}

export function parseAnalysis(value: unknown): AnalysisDto {
  const o = rec(value, 'analysis');
  const run = o.run == null ? null : rec(o.run, 'analysis.run');
  return {
    meeting_id: str(o.meeting_id, 'analysis.meeting_id'),
    state: one<AnalysisState>(o.state, STATES, 'analysis.state'),
    transcript_changed_since_run: o.transcript_changed_since_run === true,
    created: typeof o.created === 'boolean' ? o.created : undefined,
    run: run && {
      id: str(run.id, 'run.id'),
      status: one<RunDto['status']>(run.status, ['queued', 'processing', 'succeeded', 'failed'], 'run.status'),
      error: opt(run.error, 'run.error'),
      model: opt(run.model, 'run.model'),
      item_count: typeof run.item_count === 'number' ? run.item_count : 0,
      rejected: Object.fromEntries(Object.entries(rec(run.rejected ?? {}, 'run.rejected')).map(([k, v]) => [k, num(v, 'run.rejected[]')])),
      transcript_hash: str(run.transcript_hash, 'run.transcript_hash'),
    },
    items: arr(o.items, 'analysis.items').map(parseItem),
  };
}

const id = encodeURIComponent;

/** Whether the hub has meeting analysis on. A 404 (an older hub, or core with the feature off) is the same as off. */
export async function analysisEnabled(signal?: AbortSignal): Promise<boolean> {
  try {
    return rec(await request('/meeting-analysis/config', { signal }), 'config').enabled === true;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return false;
    throw error;
  }
}

export const getAnalysis = async (meetingId: string, signal?: AbortSignal): Promise<AnalysisDto> => parseAnalysis(await request(`/meetings/${id(meetingId)}/analysis`, { signal }));
export const startAnalysis = async (meetingId: string, body: { force?: boolean }): Promise<AnalysisDto> =>
  parseAnalysis(await request(`/meetings/${id(meetingId)}/analysis`, { method: 'POST', body }));
export const retryAnalysis = async (runId: string): Promise<AnalysisDto> => parseAnalysis(await request(`/meeting-analysis/runs/${id(runId)}/retry`, { method: 'POST' }));
export const confirmAction = async (itemId: string, body: { text?: string }): Promise<{ item: ItemDto; record: { kind: string; id: string } | null }> => {
  const o = rec(await request(`/meeting-analysis/items/${id(itemId)}/accept`, { method: 'POST', body }), 'accepted');
  const r = o.record == null ? null : rec(o.record, 'accepted.record');
  return { item: parseItem(o.item), record: r && { kind: str(r.kind, 'record.kind'), id: str(r.id, 'record.id') } };
};
export const dismissItem = async (itemId: string): Promise<void> => {
  await request(`/meeting-analysis/items/${id(itemId)}/dismiss`, { method: 'POST' });
};
