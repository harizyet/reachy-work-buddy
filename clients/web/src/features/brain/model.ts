// The Brain view's data contract (Phase 47C). It follows the adapter shape the owner approved for the later read-only
// Brain API (decision D4): the view asks a `BrainSource` for bounded pages of nodes, a node's detail and the explicit
// edges among nodes, and never learns where they came from. Today the only implementation is synthetic.

export type SourceType = 'memory' | 'document' | 'meeting' | 'note' | 'task' | 'reminder';

export const SOURCE_TYPES: readonly SourceType[] = ['memory', 'document', 'meeting', 'note', 'task', 'reminder'];

export const SOURCE_LABEL: Record<SourceType, string> = {
  memory: 'Memories',
  document: 'Documents',
  meeting: 'Meetings',
  note: 'Notes',
  task: 'Tasks',
  reminder: 'Reminders',
};

// Blue, cyan and violet family, plus two warmer accents so six clusters stay distinguishable (also by label and shape
// of the legend swatch, never by colour alone).
export const SOURCE_COLOR: Record<SourceType, string> = {
  memory: '#8b7bff',
  document: '#4fa3ff',
  meeting: '#33d6e8',
  note: '#b27cff',
  task: '#5be2b0',
  reminder: '#f0a8ff',
};

export interface BrainNode {
  id: string;
  type: SourceType;
  title: string;
  /** A short excerpt of the record, shown as plain text. */
  excerpt: string;
  observedAt: string;
  /** Where the record lives, so the owner can find it in its own screen. */
  sourceRef: { kind: SourceType; id: string };
  sensitivity: string;
  /** Position in the scene. Only the grouping by type is meaningful; distance carries no meaning. */
  position: [number, number, number];
}

export interface BrainEdge {
  id: string;
  from: string;
  to: string;
  /** Always `explicit` in this phase: derived from structured data, never inferred. */
  status: 'explicit';
  /** Why the link exists, in words. */
  basis: string;
}

export interface BrainFilters {
  types: ReadonlySet<SourceType>;
  query: string;
}

export interface BrainSummary {
  total: number;
  byType: Record<SourceType, number>;
  edges: number;
}

export interface BrainSource {
  /** `synthetic` data is generated for the demonstration; the view says so on screen. */
  readonly kind: 'synthetic' | 'live';
  readonly label: string;
  summary(): Promise<BrainSummary>;
  /** A bounded page; `cursor` is opaque. */
  listNodes(filters: BrainFilters, cursor: string | null, limit: number): Promise<{ nodes: BrainNode[]; next: string | null }>;
  getNode(id: string): Promise<BrainNode | null>;
  /** Only edges whose two ends are both in `nodeIds`. */
  listEdges(nodeIds: readonly string[]): Promise<BrainEdge[]>;
}

/** Case-insensitive match on title, excerpt and type name. An empty query matches everything. */
export function matchesQuery(node: BrainNode, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return node.title.toLowerCase().includes(q) || node.excerpt.toLowerCase().includes(q) || SOURCE_LABEL[node.type].toLowerCase().includes(q);
}

export function applyFilters(nodes: readonly BrainNode[], filters: BrainFilters): BrainNode[] {
  return nodes.filter((n) => filters.types.has(n.type) && matchesQuery(n, filters.query));
}

export const ALL_TYPES: ReadonlySet<SourceType> = new Set(SOURCE_TYPES);
