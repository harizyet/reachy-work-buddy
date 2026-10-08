import { SOURCE_TYPES, applyFilters, type BrainEdge, type BrainFilters, type BrainNode, type BrainSource, type BrainSummary, type SourceType } from './model';

// Seeded generator: the same seed always gives the same graph, so layouts and tests are reproducible.
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// One fixed centre per type, on a sphere, so clusters never overlap. Grouping is the only meaning of position.
export const CLUSTER_CENTER: Record<SourceType, [number, number, number]> = {
  memory: [-6.5, 1.5, 1.0],
  document: [0, 6.2, -2.8],
  meeting: [6.8, 0.8, 1.2],
  note: [-3.2, -5.6, -1.8],
  task: [3.6, -5.6, 3.2],
  reminder: [-0.5, 0.4, 7.4],
};

const SUBJECTS = ['roadmap', 'budget', 'onboarding', 'release', 'vendor', 'hiring', 'incident', 'planning', 'roster', 'pricing', 'security', 'migration'];
const VERBS = ['review', 'draft', 'confirm', 'schedule', 'summarise', 'follow up on', 'prepare', 'archive'];

const OPENERS: Record<SourceType, string> = {
  memory: 'Remembered',
  document: 'Document on',
  meeting: 'Meeting about',
  note: 'Note on',
  task: 'Task to',
  reminder: 'Reminder to',
};

function titleFor(type: SourceType, n: number, r: () => number): string {
  const subject = SUBJECTS[Math.floor(r() * SUBJECTS.length)]!;
  const verb = VERBS[Math.floor(r() * VERBS.length)]!;
  const core = type === 'task' || type === 'reminder' ? `${verb} the ${subject}` : subject;
  return `${OPENERS[type]} ${core} (synthetic ${n})`;
}

function around(center: [number, number, number], r: () => number, spread = 1.7): [number, number, number] {
  // Sum of three uniforms approximates a gaussian cheaply and deterministically.
  const g = () => (r() + r() + r() - 1.5) * spread;
  return [center[0] + g(), center[1] + g(), center[2] + g()];
}

export interface SyntheticOptions {
  seed?: number;
  count?: number;
}

export function generateGraph({ seed = 47, count = 600 }: SyntheticOptions = {}): { nodes: BrainNode[]; edges: BrainEdge[] } {
  const r = mulberry32(seed);
  const nodes: BrainNode[] = [];
  const perType: Record<SourceType, number> = { memory: 0, document: 0, meeting: 0, note: 0, task: 0, reminder: 0 };
  const weights: [SourceType, number][] = [['memory', 0.22], ['document', 0.16], ['meeting', 0.1], ['note', 0.2], ['task', 0.2], ['reminder', 0.12]];
  const base = Date.UTC(2030, 0, 1);
  for (let i = 0; i < count; i++) {
    let pick = r();
    let type: SourceType = 'note';
    for (const [t, w] of weights) {
      if (pick < w) {
        type = t;
        break;
      }
      pick -= w;
    }
    perType[type] += 1;
    const n = perType[type];
    const id = `syn-${type}-${n}`;
    nodes.push({
      id,
      type,
      title: titleFor(type, n, r),
      excerpt: `Synthetic ${type} ${n}: placeholder text generated for the demonstration. It stands for no real record.`,
      observedAt: new Date(base + Math.floor(r() * 300) * 86_400_000).toISOString(),
      sourceRef: { kind: type, id },
      sensitivity: 'work-private',
      position: around(CLUSTER_CENTER[type], r),
    });
  }
  // Explicit links, the way real structured data would give them: a task that came out of a meeting, a reminder for a task.
  const edges: BrainEdge[] = [];
  const meetings = nodes.filter((n) => n.type === 'meeting');
  const tasks = nodes.filter((n) => n.type === 'task');
  const reminders = nodes.filter((n) => n.type === 'reminder');
  tasks.forEach((t, i) => {
    const m = meetings[i % Math.max(1, meetings.length)];
    if (m && i % 3 !== 0) edges.push({ id: `e-${t.id}-${m.id}`, from: t.id, to: m.id, status: 'explicit', basis: 'The task records this meeting as its origin' });
  });
  reminders.forEach((rem, i) => {
    const t = tasks[(i * 7) % Math.max(1, tasks.length)];
    if (t && i % 2 === 0) edges.push({ id: `e-${rem.id}-${t.id}`, from: rem.id, to: t.id, status: 'explicit', basis: 'The reminder is linked to this task' });
  });
  return { nodes, edges };
}

/** A BrainSource over generated data. Paging, filtering and the edge rule match what the live source must do. */
export function createSyntheticSource(options: SyntheticOptions = {}): BrainSource {
  const { nodes, edges } = generateGraph(options);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return {
    kind: 'synthetic',
    label: 'Synthetic demonstration data',
    async summary(): Promise<BrainSummary> {
      const byType = Object.fromEntries(SOURCE_TYPES.map((t) => [t, 0])) as Record<SourceType, number>;
      for (const n of nodes) byType[n.type] += 1;
      return { total: nodes.length, byType, edges: edges.length };
    },
    async listNodes(filters: BrainFilters, cursor, limit) {
      const matching = applyFilters(nodes, filters);
      const start = cursor === null ? 0 : Number(cursor);
      if (!Number.isInteger(start) || start < 0) throw new Error('Invalid cursor');
      const page = matching.slice(start, start + Math.max(1, Math.min(limit, 1000)));
      const end = start + page.length;
      return { nodes: page, next: end < matching.length ? String(end) : null };
    },
    async getNode(id) {
      return byId.get(id) ?? null;
    },
    async listEdges(nodeIds) {
      const wanted = new Set(nodeIds);
      return edges.filter((e) => wanted.has(e.from) && wanted.has(e.to));
    },
  };
}

/** Decorative particles: positions only, with no record behind any of them. */
export function particlePositions(count: number, seed = 11): Float32Array {
  const r = mulberry32(seed);
  const out = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    // A thick spherical shell around the clusters.
    const radius = 7 + r() * 9;
    const theta = r() * Math.PI * 2;
    const phi = Math.acos(2 * r() - 1);
    out[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
    out[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
    out[i * 3 + 2] = radius * Math.cos(phi);
  }
  return out;
}
