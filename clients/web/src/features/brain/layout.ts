import { mulberry32 } from './synthetic';
import type { SourceType } from './model';
import { CLUSTER_CENTER } from './synthetic';

/** A stable hash of a string, used to seed a record's place in its cluster. */
export function hashString(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/**
 * Where a record sits in the scene: near its kind's cluster centre, offset by its id alone. The same record always lands in
 * the same place, on every machine and every visit. Only the grouping carries meaning; nothing about the content or any
 * similarity between records decides a position.
 */
export function positionFor(id: string, type: SourceType, spread = 1.7): [number, number, number] {
  const r = mulberry32(hashString(id));
  const g = () => (r() + r() + r() - 1.5) * spread;
  const c = CLUSTER_CENTER[type];
  return [c[0] + g(), c[1] + g(), c[2] + g()];
}
