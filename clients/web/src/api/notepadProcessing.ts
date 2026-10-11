import { ApiError, ApiShapeError, request } from './client';

// Notepad processing (Phase 49). The owner can send a saved note to Reachy; Reachy proposes tasks and reminders; nothing becomes a task or reminder until the
// owner accepts it here. The hub serves these routes to the signed-in owner only and the server decides everything, so this file only shapes requests and checks responses.

export type ProcessingState = 'not_processed' | 'queued' | 'processing' | 'review_required' | 'completed' | 'failed';
export type ProposalKind = 'task' | 'reminder' | 'event' | 'reference';
export type ProposalStatus = 'pending' | 'accepting' | 'accepted' | 'dismissed' | 'noted';
export type EvidenceFrom = 'note' | 'transcript' | 'both';

export interface EvidenceDto {
  kind: 'note' | 'meeting';
  quote: string;
  meeting_id: string | null;
  title: string | null;
  speaker: string | null;
}
export interface ProposalDto {
  id: string;
  note_id: string;
  kind: ProposalKind;
  status: ProposalStatus;
  text: string;
  evidence: string;
  sources: EvidenceDto[];
  evidence_from: EvidenceFrom;
  stated_time: string | null;
  due_at: string | null;
  ambiguity: string[];
  source_changed: boolean;
  record_kind: string | null;
  record_id: string | null;
  edited: boolean;
}
export interface JobMeetingDto {
  meeting_id: string;
  title: string;
  included: boolean;
  reason: string | null;
}
export interface JobDto {
  id: string;
  status: 'queued' | 'processing' | 'succeeded' | 'failed';
  error: string | null;
  model: string | null;
  proposal_count: number;
  meetings: JobMeetingDto[];
}
export interface ProcessingDto {
  note_id: string;
  state: ProcessingState;
  job: JobDto | null;
  note_changed_since_job: boolean;
  proposals: ProposalDto[];
  created?: boolean;
}
export interface MeetingLinkDto {
  id: string;
  meeting_id: string;
  source: 'explicit' | 'temporal';
  state: 'suggested' | 'confirmed';
  title_match: boolean;
  meeting_missing: boolean;
  meeting: { id: string; title: string; started_at: string | null; transcript_ready: boolean } | null;
}
export interface AcceptBody {
  text?: string;
  kind?: 'task' | 'reminder' | 'event';
  due_at?: string;
}

const STATES: readonly string[] = ['not_processed', 'queued', 'processing', 'review_required', 'completed', 'failed'];
const KINDS: readonly string[] = ['task', 'reminder', 'event', 'reference'];
const STATUSES: readonly string[] = ['pending', 'accepting', 'accepted', 'dismissed', 'noted'];
const FROM: readonly string[] = ['note', 'transcript', 'both'];
const rec = (v: unknown, what: string): Record<string, unknown> => {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new ApiShapeError(what);
  return v as Record<string, unknown>;
};
const str = (v: unknown, what: string): string => {
  if (typeof v !== 'string') throw new ApiShapeError(what);
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

export function parseProposal(value: unknown): ProposalDto {
  const p = rec(value, 'proposal');
  return {
    id: str(p.id, 'proposal.id'),
    note_id: str(p.note_id, 'proposal.note_id'),
    kind: one<ProposalKind>(p.kind, KINDS, 'proposal.kind'),
    status: one<ProposalStatus>(p.status, STATUSES, 'proposal.status'),
    text: str(p.text, 'proposal.text'),
    evidence: str(p.evidence, 'proposal.evidence'),
    sources: arr(p.sources, 'proposal.sources').map((s) => {
      const e = rec(s, 'proposal.source');
      return { kind: one<'note' | 'meeting'>(e.kind, ['note', 'meeting'], 'source.kind'), quote: str(e.quote, 'source.quote'), meeting_id: opt(e.meeting_id, 'source.meeting_id'), title: opt(e.title, 'source.title'), speaker: opt(e.speaker, 'source.speaker') };
    }),
    evidence_from: one<EvidenceFrom>(p.evidence_from, FROM, 'proposal.evidence_from'),
    stated_time: opt(p.stated_time, 'proposal.stated_time'),
    due_at: opt(p.due_at, 'proposal.due_at'),
    ambiguity: arr(p.ambiguity, 'proposal.ambiguity').map((a) => str(a, 'proposal.ambiguity[]')),
    source_changed: p.source_changed === true,
    record_kind: opt(p.record_kind, 'proposal.record_kind'),
    record_id: opt(p.record_id, 'proposal.record_id'),
    edited: p.edited === true,
  };
}

export function parseProcessing(value: unknown): ProcessingDto {
  const o = rec(value, 'processing');
  const job = o.job == null ? null : rec(o.job, 'processing.job');
  return {
    note_id: str(o.note_id, 'processing.note_id'),
    state: one<ProcessingState>(o.state, STATES, 'processing.state'),
    note_changed_since_job: o.note_changed_since_job === true,
    created: typeof o.created === 'boolean' ? o.created : undefined,
    job: job && {
      id: str(job.id, 'job.id'),
      status: one<JobDto['status']>(job.status, ['queued', 'processing', 'succeeded', 'failed'], 'job.status'),
      error: opt(job.error, 'job.error'),
      model: opt(job.model, 'job.model'),
      proposal_count: typeof job.proposal_count === 'number' ? job.proposal_count : 0,
      meetings: arr(job.meetings ?? [], 'job.meetings').map((m) => {
        const x = rec(m, 'job.meeting');
        return { meeting_id: str(x.meeting_id, 'job.meeting.id'), title: str(x.title, 'job.meeting.title'), included: x.included === true, reason: opt(x.reason, 'job.meeting.reason') };
      }),
    },
    proposals: arr(o.proposals, 'processing.proposals').map(parseProposal),
  };
}

export function parseLinks(value: unknown): MeetingLinkDto[] {
  return arr(rec(value, 'links').links, 'links.links').map((item) => {
    const l = rec(item, 'link');
    const m = l.meeting == null ? null : rec(l.meeting, 'link.meeting');
    return {
      id: str(l.id, 'link.id'),
      meeting_id: str(l.meeting_id, 'link.meeting_id'),
      source: one<'explicit' | 'temporal'>(l.source, ['explicit', 'temporal'], 'link.source'),
      state: one<'suggested' | 'confirmed'>(l.state, ['suggested', 'confirmed'], 'link.state'),
      title_match: l.title_match === true,
      meeting_missing: l.meeting_missing === true,
      meeting: m && { id: str(m.id, 'meeting.id'), title: str(m.title, 'meeting.title'), started_at: opt(m.started_at, 'meeting.started_at'), transcript_ready: m.transcript_ready === true },
    };
  });
}

const id = encodeURIComponent;

/** Whether the hub has Notepad processing on. A 404 (an older hub, or core with the feature off) is the same as off. */
export async function processingEnabled(signal?: AbortSignal): Promise<boolean> {
  try {
    return rec(await request('/notepad-processing/config', { signal }), 'config').enabled === true;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return false;
    throw error;
  }
}

export const getProcessing = async (noteId: string, signal?: AbortSignal): Promise<ProcessingDto> => parseProcessing(await request(`/notes/${id(noteId)}/processing`, { signal }));
export const sendForProcessing = async (noteId: string, body: { force?: boolean; expected_hash?: string; include_meetings?: boolean }): Promise<ProcessingDto> =>
  parseProcessing(await request(`/notes/${id(noteId)}/processing`, { method: 'POST', body }));
export const retryJob = async (jobId: string): Promise<ProcessingDto> => parseProcessing(await request(`/notepad-processing/jobs/${id(jobId)}/retry`, { method: 'POST' }));
export const acceptProposal = async (proposalId: string, body: AcceptBody): Promise<{ proposal: ProposalDto; record: { kind: string; id: string } | null }> => {
  const o = rec(await request(`/notepad-proposals/${id(proposalId)}/accept`, { method: 'POST', body }), 'accepted');
  const r = o.record == null ? null : rec(o.record, 'accepted.record');
  return { proposal: parseProposal(o.proposal), record: r && { kind: str(r.kind, 'record.kind'), id: str(r.id, 'record.id') } };
};
export const dismissProposal = async (proposalId: string): Promise<void> => {
  await request(`/notepad-proposals/${id(proposalId)}/dismiss`, { method: 'POST' });
};
export const getLinks = async (noteId: string, signal?: AbortSignal): Promise<MeetingLinkDto[]> => parseLinks(await request(`/notes/${id(noteId)}/meeting-links`, { signal }));
export const setLink = async (noteId: string, meetingId: string, state: 'confirmed' | 'rejected'): Promise<MeetingLinkDto[]> =>
  parseLinks(await request(`/notes/${id(noteId)}/meeting-links/${id(meetingId)}`, { method: 'PUT', body: { state } }));
