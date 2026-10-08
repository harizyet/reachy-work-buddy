import { request } from './client';
import { parseBrainEdges, parseBrainNode, parseBrainPage, parseBrainSummary, type BrainEdgesDto, type BrainNodeDto, type BrainPageDto, type BrainSummaryDto } from './types';

// Read-only. What the owner may see is decided on the server; nothing here asks for more.
export const fetchBrainSummary = async (signal?: AbortSignal): Promise<BrainSummaryDto> => parseBrainSummary(await request('/brain/summary', { signal }));
export const fetchBrainNodes = async (params: { types?: string; q?: string; limit: number; cursor?: string | null }, signal?: AbortSignal): Promise<BrainPageDto> => {
  const query = new URLSearchParams({ limit: String(params.limit) });
  if (params.types) query.set('types', params.types);
  if (params.q) query.set('q', params.q);
  if (params.cursor) query.set('cursor', params.cursor);
  return parseBrainPage(await request(`/brain/nodes?${query}`, { signal }));
};
export const fetchBrainNode = async (type: string, id: string, signal?: AbortSignal): Promise<BrainNodeDto> =>
  parseBrainNode(await request(`/brain/nodes/${encodeURIComponent(type)}/${encodeURIComponent(id)}`, { signal }));
export const fetchBrainEdges = async (ids: string[], signal?: AbortSignal): Promise<BrainEdgesDto> =>
  parseBrainEdges(await request(`/brain/edges?${new URLSearchParams({ ids: ids.join(',') })}`, { signal }));
