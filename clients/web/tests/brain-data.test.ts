import { describe, expect, it } from 'vitest';
import { ALL_TYPES, SOURCE_TYPES, applyFilters, matchesQuery, type SourceType } from '../src/features/brain/model';
import { CLUSTER_CENTER, createSyntheticSource, generateGraph, mulberry32, particlePositions } from '../src/features/brain/synthetic';

describe('synthetic Brain data', () => {
  it('is reproducible: the same seed gives the same graph, a different seed a different one', () => {
    const a = generateGraph({ seed: 5, count: 80 });
    const b = generateGraph({ seed: 5, count: 80 });
    const c = generateGraph({ seed: 6, count: 80 });
    expect(a).toEqual(b);
    expect(a.nodes.map((n) => n.title)).not.toEqual(c.nodes.map((n) => n.title));
    expect(mulberry32(1)()).toBe(mulberry32(1)());
  });

  it('labels every record as synthetic and invents nothing that looks real', () => {
    const { nodes } = generateGraph({ count: 200 });
    expect(nodes).toHaveLength(200);
    for (const n of nodes) {
      expect(n.id.startsWith('syn-')).toBe(true);
      expect(n.title).toMatch(/\(synthetic \d+\)$/);
      expect(n.excerpt).toMatch(/Synthetic/);
      expect(n.excerpt).toMatch(/stands for no real record/);
    }
    expect(new Set(nodes.map((n) => n.id)).size).toBe(200); // ids are unique
  });

  it('covers every source type and keeps clusters apart', () => {
    const { nodes } = generateGraph({ count: 600 });
    for (const t of SOURCE_TYPES) expect(nodes.some((n) => n.type === t)).toBe(true);
    for (const n of nodes) {
      const c = CLUSTER_CENTER[n.type];
      const dist = Math.hypot(n.position[0] - c[0], n.position[1] - c[1], n.position[2] - c[2]);
      expect(dist).toBeLessThan(4); // a node sits near its own cluster's centre
    }
    const centers = Object.values(CLUSTER_CENTER);
    for (let i = 0; i < centers.length; i++)
      for (let j = i + 1; j < centers.length; j++) expect(Math.hypot(...(centers[i]!.map((v, k) => v - centers[j]![k]!) as [number, number, number]))).toBeGreaterThan(6);
  });

  it('only draws explicit links, each with a stated basis and both ends present', () => {
    const { nodes, edges } = generateGraph({ count: 400 });
    const ids = new Set(nodes.map((n) => n.id));
    const typeOf = new Map(nodes.map((n) => [n.id, n.type]));
    expect(edges.length).toBeGreaterThan(0);
    for (const e of edges) {
      expect(e.status).toBe('explicit');
      expect(e.basis.length).toBeGreaterThan(10);
      expect(ids.has(e.from) && ids.has(e.to)).toBe(true);
    }
    // Links join the kinds that really relate: tasks to meetings, reminders to tasks. No two documents are "similar".
    for (const e of edges) expect([`${typeOf.get(e.from)}>${typeOf.get(e.to)}`]).toEqual([expect.stringMatching(/^(task>meeting|reminder>task)$/)]);
  });

  it('pages with a bounded size and an opaque cursor, filters, and never returns an edge to a node outside the request', async () => {
    const source = createSyntheticSource({ count: 120 });
    expect(source.kind).toBe('synthetic');
    const filters = { types: ALL_TYPES, query: '' };
    const first = await source.listNodes(filters, null, 50);
    expect(first.nodes).toHaveLength(50);
    expect(first.next).not.toBeNull();
    const second = await source.listNodes(filters, first.next, 50);
    const third = await source.listNodes(filters, second.next, 50);
    expect(third.next).toBeNull();
    expect(first.nodes.length + second.nodes.length + third.nodes.length).toBe(120);
    expect(new Set([...first.nodes, ...second.nodes, ...third.nodes].map((n) => n.id)).size).toBe(120);
    expect((await source.listNodes(filters, null, 100_000)).nodes.length).toBeLessThanOrEqual(120); // the server-side cap
    await expect(source.listNodes(filters, 'nonsense', 10)).rejects.toThrow('Invalid cursor');

    const meetingsOnly = await source.listNodes({ types: new Set<SourceType>(['meeting']), query: '' }, null, 1000);
    expect(meetingsOnly.nodes.every((n) => n.type === 'meeting')).toBe(true);
    const some = meetingsOnly.nodes.slice(0, 3).map((n) => n.id);
    expect(await source.listEdges(some)).toEqual([]); // links join other kinds, so none are inside meetings alone

    const all = (await source.listNodes(filters, null, 1000)).nodes;
    const edges = await source.listEdges(all.map((n) => n.id));
    const subset = new Set(all.slice(0, 40).map((n) => n.id));
    for (const e of await source.listEdges([...subset])) expect(subset.has(e.from) && subset.has(e.to)).toBe(true);
    expect(edges.length).toBeGreaterThan(0);
    expect((await source.getNode(all[0]!.id))?.id).toBe(all[0]!.id);
    expect(await source.getNode('nope')).toBeNull();
  });

  it('summarises counts that match what the filters return', async () => {
    const source = createSyntheticSource({ count: 300 });
    const summary = await source.summary();
    expect(summary.total).toBe(300);
    for (const t of SOURCE_TYPES) {
      const listed = await source.listNodes({ types: new Set<SourceType>([t]), query: '' }, null, 1000);
      expect(listed.nodes.length).toBe(summary.byType[t]);
    }
  });

  it('searches title, excerpt and type, ignoring case; an empty query matches all', () => {
    const { nodes } = generateGraph({ count: 60 });
    const meeting = nodes.find((n) => n.type === 'meeting')!;
    expect(matchesQuery(meeting, '')).toBe(true);
    expect(matchesQuery(meeting, meeting.title.toUpperCase())).toBe(true);
    expect(matchesQuery(meeting, 'MEETINGS')).toBe(true);
    expect(matchesQuery(meeting, 'placeholder text')).toBe(true);
    expect(matchesQuery(meeting, 'zzz-no-such-thing')).toBe(false);
    expect(applyFilters(nodes, { types: new Set<SourceType>(['task']), query: 'zzz-no-such-thing' })).toEqual([]);
  });

  it('decorative particles are only positions: deterministic, inside a shell, and carry no ids', () => {
    const a = particlePositions(1000, 3);
    const b = particlePositions(1000, 3);
    expect(Array.from(a)).toEqual(Array.from(b));
    expect(a.length).toBe(3000);
    for (let i = 0; i < 1000; i++) {
      const r = Math.hypot(a[i * 3]!, a[i * 3 + 1]!, a[i * 3 + 2]!);
      expect(r).toBeGreaterThanOrEqual(6.99);
      expect(r).toBeLessThanOrEqual(16.01);
    }
  });
});
