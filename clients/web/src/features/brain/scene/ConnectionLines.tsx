import { useEffect, useMemo } from 'react';
import * as THREE from 'three';
import type { BrainEdge, BrainNode } from '../model';

// Explicit links only. By default just the selected record's links are drawn, so the picture never implies more
// structure than the data holds; "show all links" draws every explicit edge.
export function ConnectionLines({ nodes, edges, selectedId, showAll }: { nodes: readonly BrainNode[]; edges: readonly BrainEdge[]; selectedId: string | null; showAll: boolean }) {
  const geometry = useMemo(() => {
    const at = new Map(nodes.map((n) => [n.id, n.position]));
    const drawn = edges.filter((e) => showAll || (selectedId !== null && (e.from === selectedId || e.to === selectedId)));
    const points: number[] = [];
    for (const e of drawn) {
      const a = at.get(e.from);
      const b = at.get(e.to);
      if (a && b) points.push(...a, ...b);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
    return g;
  }, [nodes, edges, selectedId, showAll]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <lineSegments geometry={geometry} raycast={() => null} frustumCulled={false}>
      <lineBasicMaterial color={showAll ? '#4f6fb5' : '#9fd8ff'} transparent opacity={showAll ? 0.28 : 0.85} depthWrite={false} blending={THREE.AdditiveBlending} />
    </lineSegments>
  );
}
