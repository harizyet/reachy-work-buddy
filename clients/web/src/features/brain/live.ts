import { fetchBrainEdges, fetchBrainNode, fetchBrainNodes, fetchBrainSummary } from '../../api/brain';
import type { BrainNodeDto } from '../../api/types';
import { ApiError } from '../../api/client';
import { positionFor } from './layout';
import { SOURCE_TYPES, type BrainEdge, type BrainFilters, type BrainNode, type BrainSource, type BrainSummary, type SourceType } from './model';

const isType = (value: string): value is SourceType => (SOURCE_TYPES as readonly string[]).includes(value);

function toNode(dto: BrainNodeDto): BrainNode | null {
  if (!isType(dto.type)) return null; // a kind this view does not know is left out rather than guessed at
  return {
    id: dto.id,
    type: dto.type,
    title: dto.title,
    excerpt: dto.excerpt,
    observedAt: dto.observed_at ?? '',
    sourceRef: { kind: dto.type, id: dto.source_ref.id },
    sensitivity: dto.sensitivity,
    position: positionFor(dto.id, dto.type),
  };
}

/**
 * The owner's own records, read through the hub's read-only Brain API (Phase 47D). The server revalidates every record
 * against its store and withholds what the owner may not see, so this adapter only has to ask and lay out.
 */
export function createLiveSource(): BrainSource {
  return {
    kind: 'live',
    label: 'Your records',
    async summary(): Promise<BrainSummary> {
      const s = await fetchBrainSummary();
      const byType = Object.fromEntries(SOURCE_TYPES.map((t) => [t, s.by_type[t] ?? 0])) as Record<SourceType, number>;
      return { total: s.total, byType, edges: s.edges };
    },
    async listNodes(filters: BrainFilters, cursor, limit) {
      const all = filters.types.size === SOURCE_TYPES.length;
      const page = await fetchBrainNodes({ types: all ? undefined : [...filters.types].join(','), q: filters.query.trim(), limit, cursor });
      return { nodes: page.nodes.map(toNode).filter((n): n is BrainNode => n !== null), next: page.next, truncated: page.truncated };
    },
    async getNode(id) {
      const [type, ...rest] = id.split(':');
      try {
        return toNode(await fetchBrainNode(type ?? '', rest.join(':')));
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
    async listEdges(nodeIds): Promise<BrainEdge[]> {
      const result = await fetchBrainEdges([...nodeIds]);
      return result.edges.map((e) => ({ id: e.id, from: e.from, to: e.to, status: 'explicit' as const, basis: e.basis }));
    },
  };
}

/** The route in this app where a record can be opened, when there is one. */
export function openHref(node: BrainNode): { label: string; href: string } | null {
  switch (node.type) {
    case 'note':
      return { label: 'Open in Notes', href: '#/notes' };
    case 'task':
      return { label: 'Open in To Do', href: '#/todo' };
    case 'reminder':
      return { label: 'Open in Reminders', href: '#/reminders' };
    case 'meeting':
      return { label: 'Open in Meetings', href: `#/meetings/${encodeURIComponent(node.sourceRef.id)}` };
    default:
      return null; // memories and documents have no screen of their own yet
  }
}
