import { ApiShapeError, request } from './client';

// Memory suggestions (Phase 44F). Reachy proposes short sentences from what the owner typed; nothing becomes a memory until the owner
// accepts it here. The hub serves these routes to the signed-in owner only; the server decides everything, this file only shapes requests.

export type MemoryKind = 'profile' | 'working' | 'episodic';
export type Sensitivity = 'public' | 'work-private' | 'sensitive';

export interface CandidateDto {
  id: string;
  text: string;
  rule_id: string;
  channel: string;
  proposed_type: MemoryKind;
  proposed_scope: string | null;
  sensitivity: Sensitivity;
  created_at: string;
  expires_at: string;
  conversation_id: string | null;
}
export interface CandidatesDto {
  candidates: CandidateDto[];
  capture_enabled: boolean;
}
export interface AcceptedDto {
  status: string;
  memory: { id: string; content: string; type: MemoryKind; sensitivity: Sensitivity; expires_at: string | null } | null;
}
export interface AcceptBody {
  text?: string;
  type?: MemoryKind;
  project_scope?: string | null;
  sensitivity?: Sensitivity;
  expires_in_days?: number | null;
  acknowledge_lower?: boolean;
}

const KINDS: readonly string[] = ['profile', 'working', 'episodic'];
const LEVELS: readonly string[] = ['public', 'work-private', 'sensitive'];
const rec = (v: unknown, what: string): Record<string, unknown> => {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new ApiShapeError(what);
  return v as Record<string, unknown>;
};
const text = (v: unknown, what: string): string => {
  if (typeof v !== 'string') throw new ApiShapeError(what);
  return v;
};
const oneOf = <T extends string>(v: unknown, allowed: readonly string[], what: string): T => {
  if (typeof v !== 'string' || !allowed.includes(v)) throw new ApiShapeError(what);
  return v as T;
};

export function parseCandidates(value: unknown): CandidatesDto {
  const o = rec(value, 'memory suggestions');
  if (!Array.isArray(o.candidates)) throw new ApiShapeError('memory suggestions.candidates');
  return {
    capture_enabled: o.capture_enabled === true,
    candidates: o.candidates.map((item, i) => {
      const c = rec(item, `suggestion[${i}]`);
      return {
        id: text(c.id, 'suggestion.id'),
        text: text(c.text, 'suggestion.text'),
        rule_id: text(c.rule_id, 'suggestion.rule_id'),
        channel: text(c.channel, 'suggestion.channel'),
        proposed_type: oneOf<MemoryKind>(c.proposed_type, KINDS, 'suggestion.proposed_type'),
        proposed_scope: c.proposed_scope == null ? null : text(c.proposed_scope, 'suggestion.proposed_scope'),
        sensitivity: oneOf<Sensitivity>(c.sensitivity, LEVELS, 'suggestion.sensitivity'),
        created_at: text(c.created_at, 'suggestion.created_at'),
        expires_at: text(c.expires_at, 'suggestion.expires_at'),
        conversation_id: c.conversation_id == null ? null : text(c.conversation_id, 'suggestion.conversation_id'),
      };
    }),
  };
}

export const listCandidates = async (signal?: AbortSignal): Promise<CandidatesDto> => parseCandidates(await request('/memory-candidates', { signal }));

export async function acceptCandidate(id: string, body: AcceptBody): Promise<AcceptedDto> {
  const o = rec(await request(`/memory-candidates/${encodeURIComponent(id)}/accept`, { method: 'POST', body }), 'accepted suggestion');
  const memory = o.memory == null ? null : rec(o.memory, 'accepted.memory');
  return {
    status: text(rec(o.candidate, 'accepted.candidate').status, 'accepted.status'),
    memory: memory && {
      id: text(memory.id, 'memory.id'),
      content: text(memory.content, 'memory.content'),
      type: oneOf<MemoryKind>(memory.type, KINDS, 'memory.type'),
      sensitivity: oneOf<Sensitivity>(memory.sensitivity, LEVELS, 'memory.sensitivity'),
      expires_at: memory.expires_at == null ? null : text(memory.expires_at, 'memory.expires_at'),
    },
  };
}

export const rejectCandidate = async (id: string, suppress: boolean): Promise<void> => {
  await request(`/memory-candidates/${encodeURIComponent(id)}/reject`, { method: 'POST', body: { suppress } });
};

export const forgetConversationCandidates = async (conversationId: string): Promise<number> => {
  const o = rec(await request('/memory-candidates/forget-conversation', { method: 'POST', body: { conversation_id: conversationId } }), 'forget result');
  if (typeof o.deleted !== 'number') throw new ApiShapeError('forget.deleted');
  return o.deleted;
};
