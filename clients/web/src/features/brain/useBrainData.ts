import { useQuery } from '@tanstack/react-query';
import type { BrainEdge, BrainFilters, BrainNode, BrainSource, BrainSummary } from './model';
import { ALL_TYPES } from './model';

const PAGE = 200;
const MAX_NODES = 1000; // a ceiling on what the view will hold, whatever the source offers

export interface BrainData {
  nodes: BrainNode[];
  edges: BrainEdge[];
  summary: BrainSummary;
  /** True when the source had more than the view will hold. */
  truncated: boolean;
}

// Reads the source in bounded pages, so a live source can be swapped in without the view changing.
export async function loadBrain(source: BrainSource): Promise<BrainData> {
  const filters: BrainFilters = { types: ALL_TYPES, query: '' };
  const nodes: BrainNode[] = [];
  let cursor: string | null = null;
  let truncated = false;
  do {
    const page: { nodes: BrainNode[]; next: string | null } = await source.listNodes(filters, cursor, PAGE);
    nodes.push(...page.nodes);
    cursor = page.next;
    if (nodes.length >= MAX_NODES && cursor !== null) {
      truncated = true;
      nodes.length = MAX_NODES;
      break;
    }
  } while (cursor !== null);
  const [summary, edges] = await Promise.all([source.summary(), source.listEdges(nodes.map((n) => n.id))]);
  return { nodes, edges, summary, truncated };
}

export function useBrainData(source: BrainSource) {
  // Nothing here touches the hub: the synthetic source is in memory.
  return useQuery({ queryKey: ['brain', source.kind, source.label], queryFn: () => loadBrain(source), staleTime: Infinity, retry: false });
}
