import { ApiShapeError, hubBase, request } from './client';

// Supervised meeting-minutes email (Phase 55, ADR 0039). The owner prepares a package from a finished meeting, reviews it, approves the exact package by typing SEND, and the server
// sends it through the dedicated sender after a ten-minute window. The server decides everything (the hash the approval is bound to, the sender, the state machine); this file only
// shapes requests and checks responses. The sender's credential is write-only: nothing returned here contains it.

export type DraftStatus = 'draft' | 'ready_for_review' | 'approved' | 'queued' | 'sending' | 'sent' | 'cancelled' | 'rejected' | 'failed' | 'unknown_delivery';
export interface Recipients {
  to: string[];
  cc: string[];
  bcc: string[];
}
export interface AttachmentDto {
  name: string;
  content_type: string;
  sha256: string;
  size: number;
}
export interface EventDto {
  at: string;
  event: string;
  detail: Record<string, unknown>;
}
export interface DraftDto {
  id: string;
  subject: string;
  body: string;
  status: DraftStatus;
  recipients: Recipients;
  attachments: AttachmentDto[];
  package_hash: string | null;
  approved_hash: string | null;
  sender: string | null;
  message_id: string | null;
  dispatch_at: string | null;
  sent_at: string | null;
  created_at: string;
  attempts: number;
  last_error: string | null;
  provider_response: string | null;
  meeting_id: string | null;
  meeting_title: string | null;
  meeting_changed: boolean;
  sender_ready: boolean;
  recipient_count: number;
  warnings: string[];
  events: EventDto[];
}
export interface SenderDto {
  enabled: boolean;
  configured: boolean;
  host: string;
  port: number;
  security: 'starttls' | 'none';
  from_address: string;
  username: string;
  has_credential: boolean;
  verified_at: string | null;
  verified_ok: boolean | null;
  verified_detail: string;
}
export interface GroupDto {
  id: string;
  name: string;
  addresses: string[];
}
export interface Suggestion {
  address: string;
  source: string;
}
export interface EmailConfig {
  enabled: boolean;
  sender?: SenderDto;
  send_delay_seconds?: number;
  confirm_word?: string;
}

const DRAFT_STATUSES: readonly string[] = ['draft', 'ready_for_review', 'approved', 'queued', 'sending', 'sent', 'cancelled', 'rejected', 'failed', 'unknown_delivery'];
const rec = (v: unknown, what: string): Record<string, unknown> => {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new ApiShapeError(what);
  return v as Record<string, unknown>;
};
const str = (v: unknown, what: string): string => {
  if (typeof v !== 'string') throw new ApiShapeError(what);
  return v;
};
const opt = (v: unknown, what: string): string | null => (v == null ? null : str(v, what));
const strings = (v: unknown, what: string): string[] => {
  if (!Array.isArray(v)) throw new ApiShapeError(what);
  return v.map((x) => str(x, what));
};

export function parseDraft(value: unknown): DraftDto {
  const d = rec(value, 'draft');
  const status = str(d.status, 'draft.status');
  if (!DRAFT_STATUSES.includes(status)) throw new ApiShapeError('draft.status');
  const r = d.recipients == null ? { to: [], cc: [], bcc: [] } : rec(d.recipients, 'draft.recipients');
  const source = d.source == null ? {} : rec(d.source, 'draft.source');
  return {
    id: str(d.id, 'draft.id'),
    subject: str(d.subject, 'draft.subject'),
    body: str(d.body, 'draft.body'),
    status: status as DraftStatus,
    recipients: { to: strings(r.to ?? [], 'recipients.to'), cc: strings(r.cc ?? [], 'recipients.cc'), bcc: strings(r.bcc ?? [], 'recipients.bcc') },
    attachments: (Array.isArray(d.attachments) ? d.attachments : []).map((a) => {
      const x = rec(a, 'attachment');
      return { name: str(x.name, 'attachment.name'), content_type: str(x.content_type, 'attachment.content_type'), sha256: str(x.sha256, 'attachment.sha256'), size: typeof x.size === 'number' ? x.size : 0 };
    }),
    package_hash: opt(d.package_hash, 'draft.package_hash'),
    approved_hash: opt(d.approved_hash, 'draft.approved_hash'),
    sender: opt(d.sender, 'draft.sender'),
    message_id: opt(d.message_id, 'draft.message_id'),
    dispatch_at: opt(d.dispatch_at, 'draft.dispatch_at'),
    sent_at: opt(d.sent_at, 'draft.sent_at'),
    created_at: str(d.created_at, 'draft.created_at'),
    attempts: typeof d.attempts === 'number' ? d.attempts : 0,
    last_error: opt(d.last_error, 'draft.last_error'),
    provider_response: opt(d.provider_response, 'draft.provider_response'),
    meeting_id: typeof source.meeting_id === 'string' ? source.meeting_id : null,
    meeting_title: opt(d.meeting_title, 'draft.meeting_title'),
    meeting_changed: d.meeting_changed === true,
    sender_ready: d.sender_ready === true,
    recipient_count: typeof d.recipient_count === 'number' ? d.recipient_count : 0,
    warnings: Array.isArray(d.warnings) ? strings(d.warnings, 'draft.warnings') : [],
    events: (Array.isArray(d.events) ? d.events : []).map((e) => {
      const x = rec(e, 'event');
      return { at: str(x.at, 'event.at'), event: str(x.event, 'event.event'), detail: x.detail == null ? {} : rec(x.detail, 'event.detail') };
    }),
  };
}

export function parseSender(value: unknown): SenderDto {
  const s = rec(value, 'sender');
  return {
    enabled: s.enabled === true,
    configured: s.configured === true,
    host: str(s.host ?? '', 'sender.host'),
    port: typeof s.port === 'number' ? s.port : 587,
    security: s.security === 'none' ? 'none' : 'starttls',
    from_address: str(s.from_address ?? '', 'sender.from_address'),
    username: str(s.username ?? '', 'sender.username'),
    has_credential: s.has_credential === true,
    verified_at: opt(s.verified_at, 'sender.verified_at'),
    verified_ok: typeof s.verified_ok === 'boolean' ? s.verified_ok : null,
    verified_detail: str(s.verified_detail ?? '', 'sender.verified_detail'),
  };
}

const parseGroup = (value: unknown): GroupDto => {
  const g = rec(value, 'group');
  return { id: str(g.id, 'group.id'), name: str(g.name, 'group.name'), addresses: strings(g.addresses, 'group.addresses') };
};
const id = encodeURIComponent;

export async function getEmailConfig(signal?: AbortSignal): Promise<EmailConfig> {
  const c = rec(await request('/meeting-email/config', { signal }), 'config');
  return { enabled: c.enabled === true, sender: c.sender == null ? undefined : parseSender(c.sender), send_delay_seconds: typeof c.send_delay_seconds === 'number' ? c.send_delay_seconds : 600, confirm_word: typeof c.confirm_word === 'string' ? c.confirm_word : 'SEND' };
}
export const getSender = async (signal?: AbortSignal): Promise<SenderDto> => parseSender(await request('/meeting-email/sender', { signal }));
export interface SenderInput {
  host: string;
  port: number;
  security: 'starttls' | 'none';
  from_address: string;
  username: string;
  password?: string;
  clear_password?: boolean;
}
export const saveSender = async (input: SenderInput): Promise<SenderDto> => parseSender(await request('/meeting-email/sender', { method: 'PUT', body: input }));
export const verifySender = async (): Promise<{ ok: boolean; detail: string; sender: SenderDto }> => {
  const r = rec(await request('/meeting-email/sender/verify', { method: 'POST', body: {} }), 'verify');
  return { ok: r.ok === true, detail: str(r.detail ?? '', 'verify.detail'), sender: parseSender(r.sender) };
};
export const setSenderEnabled = async (enabled: boolean): Promise<SenderDto> => parseSender(await request('/meeting-email/sender/enabled', { method: 'PUT', body: { enabled } }));
export const disconnectSender = async (): Promise<SenderDto> => parseSender(await request('/meeting-email/sender', { method: 'DELETE' }));

export const listGroups = async (signal?: AbortSignal): Promise<GroupDto[]> => {
  const r = await request('/meeting-email/groups', { signal });
  if (!Array.isArray(r)) throw new ApiShapeError('groups');
  return r.map(parseGroup);
};
export const saveGroup = async (name: string, addresses: string[], groupId?: string): Promise<GroupDto> =>
  parseGroup(await request(groupId ? `/meeting-email/groups/${id(groupId)}` : '/meeting-email/groups', { method: groupId ? 'PUT' : 'POST', body: { name, addresses } }));
export const deleteGroup = async (groupId: string): Promise<void> => {
  await request(`/meeting-email/groups/${id(groupId)}`, { method: 'DELETE' });
};

export interface PrepareInput {
  allow_sensitive?: boolean;
  include_pdf?: boolean;
  to?: string[];
  cc?: string[];
  bcc?: string[];
  group_ids?: string[];
}
export const prepareEmail = async (meetingId: string, input: PrepareInput): Promise<DraftDto> => parseDraft(await request(`/meetings/${id(meetingId)}/email/prepare`, { method: 'POST', body: input }));
export const getSuggestions = async (meetingId: string, signal?: AbortSignal): Promise<Suggestion[]> => {
  const r = await request(`/meetings/${id(meetingId)}/email/suggestions`, { signal });
  if (!Array.isArray(r)) throw new ApiShapeError('suggestions');
  return r.map((s) => {
    const x = rec(s, 'suggestion');
    return { address: str(x.address, 'suggestion.address'), source: str(x.source, 'suggestion.source') };
  });
};
export const listDrafts = async (meetingId: string, signal?: AbortSignal): Promise<DraftDto[]> => {
  const r = await request(`/meeting-email/drafts?meeting_id=${id(meetingId)}`, { signal });
  if (!Array.isArray(r)) throw new ApiShapeError('drafts');
  return r.map(parseDraft);
};
export const getDraft = async (draftId: string, signal?: AbortSignal): Promise<DraftDto> => parseDraft(await request(`/meeting-email/drafts/${id(draftId)}`, { signal }));
export interface EditInput {
  to?: string[];
  cc?: string[];
  bcc?: string[];
  group_ids?: string[];
  subject?: string;
  body?: string;
  include_pdf?: boolean;
  refresh?: boolean;
}
export const editDraft = async (draftId: string, input: EditInput): Promise<DraftDto> => parseDraft(await request(`/meeting-email/drafts/${id(draftId)}`, { method: 'PUT', body: input }));
export const approveDraft = async (draftId: string, packageHash: string, confirmation: string): Promise<DraftDto> =>
  parseDraft(await request(`/meeting-email/drafts/${id(draftId)}/approve`, { method: 'POST', body: { package_hash: packageHash, confirmation } }));
export const queueDraft = async (draftId: string): Promise<DraftDto> => parseDraft(await request(`/meeting-email/drafts/${id(draftId)}/queue`, { method: 'POST' }));
export const cancelSend = async (draftId: string): Promise<DraftDto> => parseDraft(await request(`/meeting-email/drafts/${id(draftId)}/cancel-send`, { method: 'POST' }));
export const discardDraft = async (draftId: string): Promise<DraftDto> => parseDraft(await request(`/meeting-email/drafts/${id(draftId)}/discard`, { method: 'POST' }));
export const resolveDraft = async (draftId: string, delivered: boolean): Promise<DraftDto> =>
  parseDraft(await request(`/meeting-email/drafts/${id(draftId)}/resolve`, { method: 'POST', body: { delivered } }));
/** The attachment exactly as it will be sent, behind the owner cookie; a relative URL keeps it right under /hub/. */
export const attachmentUrl = (draftId: string, name: string) => `${hubBase()}/meeting-email/drafts/${id(draftId)}/attachments/${id(name)}`;

/** "10 minutes", "1 minute" or, for a short test window, "5 seconds": the undo window in words. */
export function delayText(seconds: number): string {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} second${Math.round(seconds) === 1 ? '' : 's'}`;
  const minutes = Math.round(seconds / 60);
  return `${minutes} minute${minutes === 1 ? '' : 's'}`;
}
