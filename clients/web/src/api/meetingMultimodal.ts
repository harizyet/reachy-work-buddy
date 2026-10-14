import { ApiError, ApiShapeError, request } from './client';

// Multimodal meeting intelligence (Phase 53). The owner attaches documents to a finished meeting; Reachy ESTIMATES which page each stretch of the transcript was about, labels how well
// the evidence supports each estimate, and answers questions and lists findings from both sources with separate citations. The estimate is never a statement of what was on a screen.
// The hub serves these routes to the signed-in owner only and the server decides everything, so this file only shapes requests and checks responses.

export type Certainty = 'high' | 'medium' | 'low' | 'unknown';
export type Authority = 'suggested' | 'owner' | 'owner_stale';
export type ReviewStatus = 'suggested' | 'confirmed' | 'replaced' | 'no_slide' | 'removed' | 'needs_revalidation';
export type RunState = 'not_run' | 'queued' | 'processing' | 'succeeded' | 'failed';
export type ItemKind = 'discussion' | 'decision' | 'disagreement' | 'open_question' | 'action';
export type ItemStatus = 'pending' | 'accepting' | 'accepted' | 'dismissed' | 'noted';
export type Decision = 'confirmed' | 'replaced' | 'no_slide' | 'removed';

export interface AttachedDocument {
  document_id: string;
  title: string;
  filename: string;
  state: string;
  ready: boolean;
  page_count: number | null;
  tier: string | null;
  sensitivity: string;
  project_scope: string | null;
  error_code: string | null;
}
export interface Alternative {
  document_id: string;
  document_title: string;
  page: number;
  title: string | null;
}
export interface Contradiction {
  document_id: string;
  page: number;
  slide_quote: string;
  spoken_quote: string;
}
export interface Suggestion {
  document_id: string;
  document_title: string;
  page: number;
  slide_title: string | null;
  certainty: Certainty;
  method: 'explicit_reference' | 'semantic' | 'none';
  relation: 'supports' | 'contradicts' | 'unresolved';
  reason: string;
  model_note: string | null;
  shared_terms: string[];
  explicit_refs: string[];
  contradictions: Contradiction[];
  alternatives: Alternative[];
}
export interface Shown {
  document_id: string;
  document_title: string;
  page: number;
  slide_title: string | null;
  authority: Authority;
  certainty: Certainty | null;
}
export interface Owner {
  decision: Decision;
  valid: boolean;
  document_id: string | null;
  page: number | null;
}
export interface WindowDto {
  window_key: string;
  segment_ids: number[];
  start: number;
  end: number;
  suggestion: Suggestion | null;
  owner: Owner | null;
  review_status: ReviewStatus;
  shown: Shown | null;
  source_changed: boolean;
  document_changed: boolean;
  stale: boolean;
}
export interface RunDto {
  id: string;
  status: 'queued' | 'processing' | 'succeeded' | 'failed';
  error: string | null;
  model: string | null;
  stats: Record<string, number>;
}
export interface Cite {
  source: 'transcript' | 'document';
  quote: string;
  segment: number | null;
  start: number | null;
  speaker: string | null;
  document_id: string | null;
  page: number | null;
}
export interface FindingDto {
  id: string;
  kind: ItemKind;
  status: ItemStatus;
  text: string;
  evidence: Cite[];
  assignee: string | null;
  stated_time: string | null;
  ambiguity: string[];
  support: 'stated' | 'uncertain';
  sensitivity: string;
  source_changed: boolean;
  document_changed: boolean;
  task_text: string | null;
  record_id: string | null;
}
export interface Unaddressed {
  document_id: string;
  document_title: string;
  page: number;
}
export interface Overview {
  meeting_id: string;
  sensitivity: string;
  documents: AttachedDocument[];
  transcript_hash: string | null;
  alignment: { state: RunState; run: RunDto | null; transcript_changed: boolean; documents_changed: boolean; documents_added: boolean };
  analysis: { state: RunState; run: RunDto | null; items: FindingDto[] };
  windows: WindowDto[];
  unaddressed: Unaddressed[];
  disclaimer: string;
  created?: boolean;
}
export interface AnswerPart {
  kind: 'document' | 'speaker' | 'decision' | 'inference' | 'unknown';
  label: string;
  text: string;
  cites: string[];
  note: string | null;
}
export interface Citation {
  id: string;
  source: 'transcript' | 'document';
  excerpt: string;
  window_key?: string;
  start?: number;
  end?: number;
  speaker?: string | null;
  document_id?: string;
  title?: string;
  page?: number;
  locator?: string;
}
export interface Answer {
  answered: boolean;
  abstained: boolean;
  message: string | null;
  parts: AnswerPart[];
  citations: Record<string, Citation>;
  associations: { transcript: string; document: string; authority: string; certainty: Certainty | null; meaning: string }[];
  possible_disagreements: (Contradiction & { window_key: string })[];
  caveats: string[];
  sensitivity: string;
  model: string | null;
  latency_ms: number;
}

const STATES: readonly string[] = ['not_run', 'queued', 'processing', 'succeeded', 'failed'];
const rec = (v: unknown, what: string): Record<string, unknown> => {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new ApiShapeError(what);
  return v as Record<string, unknown>;
};
const arr = (v: unknown, what: string): unknown[] => {
  if (!Array.isArray(v)) throw new ApiShapeError(what);
  return v;
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
const state = (v: unknown, what: string): RunState => {
  if (typeof v !== 'string' || !STATES.includes(v)) throw new ApiShapeError(what);
  return v as RunState;
};

function parseRun(value: unknown): RunDto | null {
  if (value == null) return null;
  const r = rec(value, 'run');
  return {
    id: str(r.id, 'run.id'),
    status: str(r.status, 'run.status') as RunDto['status'],
    error: opt(r.error, 'run.error'),
    model: opt(r.model, 'run.model'),
    stats: Object.fromEntries(Object.entries(rec(r.stats ?? {}, 'run.stats')).filter(([, v]) => typeof v === 'number')) as Record<string, number>,
  };
}
function parseCite(value: unknown): Cite {
  const c = rec(value, 'cite');
  return {
    source: str(c.source, 'cite.source') as Cite['source'],
    quote: str(c.quote, 'cite.quote'),
    segment: typeof c.segment === 'number' ? c.segment : null,
    start: typeof c.start === 'number' ? c.start : null,
    speaker: opt(c.speaker, 'cite.speaker'),
    document_id: opt(c.document_id, 'cite.document_id'),
    page: typeof c.page === 'number' ? c.page : null,
  };
}
export function parseFinding(value: unknown): FindingDto {
  const i = rec(value, 'finding');
  return {
    id: str(i.id, 'finding.id'),
    kind: str(i.kind, 'finding.kind') as ItemKind,
    status: str(i.status, 'finding.status') as ItemStatus,
    text: str(i.text, 'finding.text'),
    evidence: arr(i.evidence, 'finding.evidence').map(parseCite),
    assignee: opt(i.assignee, 'finding.assignee'),
    stated_time: opt(i.stated_time, 'finding.stated_time'),
    ambiguity: arr(i.ambiguity ?? [], 'finding.ambiguity').map((a) => str(a, 'finding.ambiguity[]')),
    support: i.support === 'stated' ? 'stated' : 'uncertain',
    sensitivity: str(i.sensitivity, 'finding.sensitivity'),
    source_changed: i.source_changed === true,
    document_changed: i.document_changed === true,
    task_text: opt(i.task_text, 'finding.task_text'),
    record_id: opt(i.record_id, 'finding.record_id'),
  };
}
function parseSuggestion(value: unknown): Suggestion | null {
  if (value == null) return null;
  const s = rec(value, 'suggestion');
  return {
    document_id: str(s.document_id, 'suggestion.document_id'),
    document_title: str(s.document_title, 'suggestion.document_title'),
    page: num(s.page, 'suggestion.page'),
    slide_title: opt(s.slide_title, 'suggestion.slide_title'),
    certainty: str(s.certainty, 'suggestion.certainty') as Certainty,
    method: str(s.method, 'suggestion.method') as Suggestion['method'],
    relation: str(s.relation, 'suggestion.relation') as Suggestion['relation'],
    reason: str(s.reason ?? '', 'suggestion.reason'),
    model_note: opt(s.model_note, 'suggestion.model_note'),
    shared_terms: arr(s.shared_terms ?? [], 'suggestion.shared_terms').map((t) => str(t, 'term')),
    explicit_refs: arr(s.explicit_refs ?? [], 'suggestion.explicit_refs').map((t) => str(t, 'ref')),
    contradictions: arr(s.contradictions ?? [], 'suggestion.contradictions').map((c) => {
      const x = rec(c, 'contradiction');
      return { document_id: str(x.document_id, 'c.document_id'), page: num(x.page, 'c.page'), slide_quote: str(x.slide_quote, 'c.slide_quote'), spoken_quote: str(x.spoken_quote, 'c.spoken_quote') };
    }),
    alternatives: arr(s.alternatives ?? [], 'suggestion.alternatives').map((a) => {
      const x = rec(a, 'alternative');
      return { document_id: str(x.document_id, 'alt.document_id'), document_title: str(x.document_title, 'alt.document_title'), page: num(x.page, 'alt.page'), title: opt(x.title, 'alt.title') };
    }),
  };
}
export function parseWindow(value: unknown): WindowDto {
  const w = rec(value, 'window');
  const shown = w.shown == null ? null : rec(w.shown, 'window.shown');
  const owner = w.owner == null ? null : rec(w.owner, 'window.owner');
  return {
    window_key: str(w.window_key, 'window.window_key'),
    segment_ids: arr(w.segment_ids, 'window.segment_ids').map((n) => num(n, 'segment')),
    start: num(w.start, 'window.start'),
    end: num(w.end, 'window.end'),
    suggestion: parseSuggestion(w.suggestion),
    owner: owner && { decision: str(owner.decision, 'owner.decision') as Decision, valid: owner.valid === true, document_id: opt(owner.document_id, 'owner.document_id'), page: typeof owner.page === 'number' ? owner.page : null },
    review_status: str(w.review_status, 'window.review_status') as ReviewStatus,
    shown: shown && {
      document_id: str(shown.document_id, 'shown.document_id'),
      document_title: str(shown.document_title ?? '', 'shown.document_title'),
      page: num(shown.page, 'shown.page'),
      slide_title: opt(shown.slide_title, 'shown.slide_title'),
      authority: str(shown.authority, 'shown.authority') as Authority,
      certainty: shown.certainty == null ? null : (str(shown.certainty, 'shown.certainty') as Certainty),
    },
    source_changed: w.source_changed === true,
    document_changed: w.document_changed === true,
    stale: w.stale === true,
  };
}
export function parseOverview(value: unknown): Overview {
  const o = rec(value, 'overview');
  const a = rec(o.alignment, 'overview.alignment');
  const n = rec(o.analysis, 'overview.analysis');
  return {
    meeting_id: str(o.meeting_id, 'overview.meeting_id'),
    sensitivity: str(o.sensitivity, 'overview.sensitivity'),
    documents: arr(o.documents, 'overview.documents').map((d) => {
      const x = rec(d, 'document');
      return {
        document_id: str(x.document_id, 'document.document_id'), title: str(x.title, 'document.title'), filename: str(x.filename, 'document.filename'), state: str(x.state, 'document.state'),
        ready: x.ready === true, page_count: typeof x.page_count === 'number' ? x.page_count : null, tier: opt(x.tier, 'document.tier'), sensitivity: str(x.sensitivity, 'document.sensitivity'),
        project_scope: opt(x.project_scope, 'document.project_scope'), error_code: opt(x.error_code, 'document.error_code'),
      };
    }),
    transcript_hash: opt(o.transcript_hash, 'overview.transcript_hash'),
    alignment: { state: state(a.state, 'alignment.state'), run: parseRun(a.run), transcript_changed: a.transcript_changed === true, documents_changed: a.documents_changed === true, documents_added: a.documents_added === true },
    analysis: { state: state(n.state, 'analysis.state'), run: parseRun(n.run), items: arr(n.items, 'analysis.items').map(parseFinding) },
    windows: arr(o.windows, 'overview.windows').map(parseWindow),
    unaddressed: arr(o.unaddressed, 'overview.unaddressed').map((u) => {
      const x = rec(u, 'unaddressed');
      return { document_id: str(x.document_id, 'u.document_id'), document_title: str(x.document_title, 'u.document_title'), page: num(x.page, 'u.page') };
    }),
    disclaimer: str(o.disclaimer ?? '', 'overview.disclaimer'),
    created: typeof o.created === 'boolean' ? o.created : undefined,
  };
}
export function parseAnswer(value: unknown): Answer {
  const o = rec(value, 'answer');
  return {
    answered: o.answered === true,
    abstained: o.abstained === true,
    message: opt(o.message, 'answer.message'),
    parts: arr(o.parts, 'answer.parts').map((p) => {
      const x = rec(p, 'part');
      return { kind: str(x.kind, 'part.kind') as AnswerPart['kind'], label: str(x.label, 'part.label'), text: str(x.text, 'part.text'), cites: arr(x.cites ?? [], 'part.cites').map((c) => str(c, 'cite')), note: opt(x.note, 'part.note') };
    }),
    citations: Object.fromEntries(Object.entries(rec(o.citations ?? {}, 'answer.citations')).map(([k, v]) => [k, rec(v, 'citation') as unknown as Citation])),
    associations: arr(o.associations ?? [], 'answer.associations') as Answer['associations'],
    possible_disagreements: arr(o.possible_disagreements ?? [], 'answer.possible_disagreements') as Answer['possible_disagreements'],
    caveats: arr(o.caveats ?? [], 'answer.caveats').map((c) => str(c, 'caveat')),
    sensitivity: str(o.sensitivity, 'answer.sensitivity'),
    model: opt(o.model, 'answer.model'),
    latency_ms: typeof o.latency_ms === 'number' ? o.latency_ms : 0,
  };
}

const id = encodeURIComponent;
const base = (meetingId: string) => `/meetings/${id(meetingId)}/multimodal`;

/** Whether the hub has the feature on. A 404 (an older hub, or core with the feature off) is the same as off. */
export async function multimodalEnabled(signal?: AbortSignal): Promise<boolean> {
  try {
    return rec(await request('/meeting-multimodal/config', { signal }), 'config').enabled === true;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return false;
    throw error;
  }
}

export const getOverview = async (meetingId: string, signal?: AbortSignal): Promise<Overview> => parseOverview(await request(base(meetingId), { signal }));
export const attachDocument = async (meetingId: string, documentId: string): Promise<void> => {
  await request(`${base(meetingId)}/documents`, { method: 'POST', body: { document_id: documentId } });
};
export const detachDocument = async (meetingId: string, documentId: string): Promise<void> => {
  await request(`${base(meetingId)}/documents/${id(documentId)}`, { method: 'DELETE' });
};
export const startAlignment = async (meetingId: string, force: boolean): Promise<Overview> => parseOverview(await request(`${base(meetingId)}/alignment`, { method: 'POST', body: { force } }));
export const startCombinedAnalysis = async (meetingId: string, force: boolean): Promise<Overview> => parseOverview(await request(`${base(meetingId)}/analysis`, { method: 'POST', body: { force } }));
export const retryRun = async (runId: string): Promise<Overview> => parseOverview(await request(`/meeting-multimodal/runs/${id(runId)}/retry`, { method: 'POST' }));
export const reviewWindow = async (meetingId: string, key: string, body: { decision: Decision; document_id?: string; page?: number }): Promise<WindowDto> =>
  parseWindow(rec(await request(`${base(meetingId)}/windows/${id(key)}/review`, { method: 'PUT', body }), 'review').window);
export const withdrawReview = async (meetingId: string, key: string): Promise<void> => {
  await request(`${base(meetingId)}/windows/${id(key)}/review`, { method: 'DELETE' });
};
export const askAcross = async (meetingId: string, question: string): Promise<Answer> => parseAnswer(await request(`${base(meetingId)}/ask`, { method: 'POST', body: { question } }));
export const confirmFinding = async (itemId: string, body: { text?: string }): Promise<{ item: FindingDto; record: { kind: string; id: string } | null }> => {
  const o = rec(await request(`/meeting-multimodal/items/${id(itemId)}/accept`, { method: 'POST', body }), 'accepted');
  const r = o.record == null ? null : rec(o.record, 'accepted.record');
  return { item: parseFinding(o.item), record: r && { kind: str(r.kind, 'record.kind'), id: str(r.id, 'record.id') } };
};
export const dismissFinding = async (itemId: string): Promise<void> => {
  await request(`/meeting-multimodal/items/${id(itemId)}/dismiss`, { method: 'POST' });
};
