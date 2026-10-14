import { ApiError, ApiShapeError, request } from './client';

// Document library (Phase 50). The owner uploads files to Reachy, which keeps the original, has them read by the document worker, and answers from them. The hub serves these routes to the
// signed-in owner only and sets the access ceiling itself; the server decides everything, so this file shapes requests and checks that responses have the shape the pages rely on.

/** The file types the library accepts (shared/models/document_types.py; a core test keeps this list identical to it). A type is accepted by its content, not its name. */
export const ACCEPTED_FILES = '.pdf,.png,.jpg,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.rtf,.odt,.odp,.ods,.epub,.html,.csv,.tsv,.jpeg,.htm';
/** Presentation files the reader was not shown to parse: refused with the way forward. */
export const UNREAD_PRESENTATION = /\.(pps|ppsx|pptm|key|pages|numbers)$/i;

export type DocumentState = 'uploaded' | 'queued' | 'processing' | 'ready' | 'partial' | 'failed' | 'deleting';
export type Sensitivity = 'public' | 'work-private' | 'sensitive';
export type Priority = 'background' | 'normal' | 'interactive';
export type Tier = 'flash' | 'basic' | 'standard' | 'advanced';
export type SummaryStyle = 'ordinary' | 'executive' | 'technical';

export interface DocumentDto {
  id: string;
  title: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  source_hash: string;
  sensitivity: Sensitivity;
  project_scope: string | null;
  state: DocumentState;
  processing_priority: Priority;
  tier: Tier | null;
  page_count: number | null;
  error_code: string | null;
  next_tier: Tier | null;
  created_at: string;
  updated_at: string;
}
export interface SectionDto {
  pages: string;
  start_page: number;
  end_page: number;
  summary: string;
  locator: string | null;
}
export interface SummaryDto {
  id: string;
  document_id: string;
  style: SummaryStyle;
  status: 'running' | 'ready' | 'failed';
  text: string;
  sections: SectionDto[];
  pages_covered: string | null;
  page_count: number | null;
  truncated: boolean;
  source_hash: string;
  tier: Tier;
  sensitivity: Sensitivity;
  model: string | null;
  stale: boolean;
  current: boolean;
  error_code: string | null;
  created_at: string;
}
export interface HitDto {
  snippet: string;
  page: number | null;
  locator: string | null;
}
export interface SearchDto {
  document_id: string;
  title: string;
  hits: HitDto[];
  complete: boolean;
}
export interface CitationDto {
  document_id: string;
  title: string;
  page: number;
  locator: string | null;
}
export interface AnswerDto {
  reply: string;
  context_document: string | null;
  citations: CitationDto[];
}

const STATES: DocumentState[] = ['uploaded', 'queued', 'processing', 'ready', 'partial', 'failed', 'deleting'];
const q = encodeURIComponent;
const base = '/document-library/documents';

function record(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new ApiShapeError(what);
  return value as Record<string, unknown>;
}

export function parseDocument(value: unknown): DocumentDto {
  const o = record(value, 'document');
  if (typeof o.id !== 'string' || typeof o.title !== 'string' || typeof o.state !== 'string' || !STATES.includes(o.state as DocumentState)) throw new ApiShapeError('document');
  return o as unknown as DocumentDto;
}
function parseList<T>(value: unknown, what: string, one: (v: unknown) => T): T[] {
  if (!Array.isArray(value)) throw new ApiShapeError(what);
  return value.map(one);
}
export function parseSummary(value: unknown): SummaryDto {
  const o = record(value, 'summary');
  if (typeof o.id !== 'string' || typeof o.status !== 'string' || !Array.isArray(o.sections)) throw new ApiShapeError('summary');
  return o as unknown as SummaryDto;
}

export async function libraryEnabled(signal?: AbortSignal): Promise<boolean> {
  const o = record(await request('/document-library/config', { signal }), 'config');
  return o.enabled === true;
}
export const listDocuments = async (signal?: AbortSignal): Promise<DocumentDto[]> => parseList(await request(base, { signal }), 'documents', parseDocument);
export const getDocument = async (id: string, signal?: AbortSignal): Promise<DocumentDto> => parseDocument(await request(`${base}/${q(id)}`, { signal }));

export interface UploadInput {
  file: File;
  title?: string;
  sensitivity: Sensitivity;
  project_scope?: string;
  processing_priority: Priority;
}
export async function uploadDocument(input: UploadInput): Promise<DocumentDto> {
  const form = new FormData();
  form.append('file', input.file);
  if (input.title?.trim()) form.append('title', input.title.trim());
  form.append('sensitivity', input.sensitivity);
  if (input.project_scope?.trim()) form.append('project_scope', input.project_scope.trim());
  form.append('processing_priority', input.processing_priority);
  return parseDocument(await request(base, { method: 'POST', body: form }));
}
export interface DocumentPatch {
  title?: string;
  project_scope?: string | null;
  sensitivity?: Sensitivity;
  processing_priority?: Priority;
}
export const patchDocument = async (id: string, patch: DocumentPatch): Promise<DocumentDto> => parseDocument(await request(`${base}/${q(id)}`, { method: 'PATCH', body: patch }));
export const reprocessDocument = async (id: string, tier?: Tier): Promise<DocumentDto> =>
  parseDocument(await request(`${base}/${q(id)}/reprocess`, { method: 'POST', body: tier ? { tier } : {} }));
export const deleteDocument = async (id: string): Promise<void> => {
  await request(`${base}/${q(id)}`, { method: 'DELETE' });
};
export async function searchDocument(id: string, query: string): Promise<SearchDto> {
  const o = record(await request(`${base}/${q(id)}/search`, { method: 'POST', body: { query, limit: 10 } }), 'search');
  if (!Array.isArray(o.hits)) throw new ApiShapeError('search');
  return o as unknown as SearchDto;
}
export const listSummaries = async (id: string, signal?: AbortSignal): Promise<SummaryDto[]> => parseList(await request(`${base}/${q(id)}/summaries`, { signal }), 'summaries', parseSummary);
export const startSummary = async (id: string, style: SummaryStyle, force = false): Promise<SummaryDto> =>
  parseSummary(await request(`${base}/${q(id)}/summaries`, { method: 'POST', body: { style, force } }));

/** A question about one attached document, sent as an ordinary typed web message. The answer comes back with the pages whose excerpts were used. */
export async function askDocument(user: string, documentId: string, text: string): Promise<AnswerDto> {
  const o = record(await request('/messages', { method: 'POST', body: { user_id: user, channel: 'web', input_modality: 'text', text, context_document_id: documentId } }), 'answer');
  if (typeof o.reply !== 'string') throw new ApiShapeError('answer');
  return { reply: o.reply, context_document: typeof o.context_document === 'string' ? o.context_document : null, citations: Array.isArray(o.citations) ? (o.citations as CitationDto[]) : [] };
}

export function describeError(error: unknown): string {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : 'Something went wrong';
}

// --- Extraction inspector -----------------------------------------------------------------------------
// What MinerU extracted for one page, MinerU's own picture of the original page and its blocks, and downloads of its outputs. Derived extraction: the original is what counts.

export interface BlockDto {
  block: number;
  type: string;
  bbox: [number, number, number, number] | null; // fractions of the page: left, top, right, bottom
}
export interface InspectPageDto {
  document_id: string;
  title: string;
  source_hash: string;
  evidence_type: string;
  state: DocumentState;
  tier: Tier;
  next_tier: Tier | null;
  source_type: string;
  page: number;
  page_count: number;
  page_image: boolean;
  width_pt: number | null;
  height_pt: number | null;
  blocks: BlockDto[];
  markdown: string;
  html: string;
}
export type ExportKind = 'markdown' | 'html' | 'content_list' | 'middle_json';

export async function getInspectPage(id: string, page: number, signal?: AbortSignal): Promise<InspectPageDto> {
  const o = record(await request(`${base}/${q(id)}/inspect/pages/${page}`, { signal }), 'inspect');
  if (typeof o.page !== 'number' || typeof o.markdown !== 'string' || typeof o.html !== 'string' || !Array.isArray(o.blocks)) throw new ApiShapeError('inspect');
  return o as unknown as InspectPageDto;
}
/** MinerU's rendering of the original page (a block's crop when `block` is given), as an image to show. */
export const getPageImage = (id: string, page: number, block?: number, signal?: AbortSignal): Promise<Blob> =>
  request<Blob>(`${base}/${q(id)}/inspect/pages/${page}${block ? `/blocks/${block}` : ''}/image`, { asBlob: true, signal });
export const getExport = (id: string, kind: ExportKind): Promise<Blob> => request<Blob>(`${base}/${q(id)}/export?format=${kind}`, { asBlob: true });
export const getOriginal = (id: string): Promise<Blob> => request<Blob>(`${base}/${q(id)}/original`, { asBlob: true });
