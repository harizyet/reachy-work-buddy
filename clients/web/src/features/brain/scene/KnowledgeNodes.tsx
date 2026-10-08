import type { ThreeEvent } from '@react-three/fiber';
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { SOURCE_COLOR, type BrainNode } from '../model';

const BASE = 0.11;

export interface NodesProps {
  nodes: readonly BrainNode[];
  /** Ids that pass the current search and filters; the rest are dimmed, not removed, so the shape stays readable. */
  visible: ReadonlySet<string>;
  /** With a real bloom pass the soft halos are mostly redundant, so they are dimmed. */
  bloom?: boolean;
  selectedId: string | null;
  hoveredId: string | null;
  onSelect(id: string | null): void;
  onHover(id: string | null): void;
}

// Real records, one instance each. Colours, sizes and dimming are written when the data or the selection changes,
// never per frame, and the whole set is two draw calls (cores and soft halos).
export function KnowledgeNodes({ nodes, visible, selectedId, hoveredId, onSelect, onHover, bloom = false }: NodesProps) {
  const cores = useRef<THREE.InstancedMesh>(null);
  const halos = useRef<THREE.InstancedMesh>(null);
  const coreGeometry = useMemo(() => new THREE.SphereGeometry(BASE, 12, 8), []);
  const haloGeometry = useMemo(() => new THREE.SphereGeometry(BASE * 2.6, 10, 6), []);
  useEffect(
    () => () => {
      coreGeometry.dispose();
      haloGeometry.dispose();
    },
    [coreGeometry, haloGeometry],
  );

  useLayoutEffect(() => {
    const c = cores.current;
    const h = halos.current;
    if (!c || !h) return;
    const m = new THREE.Matrix4();
    const color = new THREE.Color();
    nodes.forEach((n, i) => {
      const on = visible.has(n.id);
      const emphasis = n.id === selectedId ? 2.4 : n.id === hoveredId ? 1.7 : 1;
      const scale = (on ? 1 : 0.45) * emphasis;
      m.makeScale(scale, scale, scale).setPosition(n.position[0], n.position[1], n.position[2]);
      c.setMatrixAt(i, m);
      color.set(SOURCE_COLOR[n.type]);
      if (!on) color.multiplyScalar(0.22);
      c.setColorAt(i, color);
      m.makeScale(on ? emphasis : 0.001, on ? emphasis : 0.001, on ? emphasis : 0.001).setPosition(n.position[0], n.position[1], n.position[2]);
      h.setMatrixAt(i, m);
      color.set(SOURCE_COLOR[n.type]);
      h.setColorAt(i, color);
    });
    for (const mesh of [c, h]) {
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      mesh.computeBoundingSphere();
    }
  }, [nodes, visible, selectedId, hoveredId]);

  const pick = (e: ThreeEvent<PointerEvent | MouseEvent>) => (e.instanceId === undefined ? null : (nodes[e.instanceId] ?? null));
  return (
    <group>
      <instancedMesh key={`halo-${nodes.length}`} ref={halos} args={[haloGeometry, undefined, nodes.length]} raycast={() => null} frustumCulled={false}>
        <meshBasicMaterial transparent opacity={bloom ? 0.04 : 0.1} depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
      </instancedMesh>
      <instancedMesh
        key={`core-${nodes.length}`}
        ref={cores}
        args={[coreGeometry, undefined, nodes.length]}
        frustumCulled={false}
        onPointerMove={(e) => {
          e.stopPropagation();
          const n = pick(e);
          onHover(n && visible.has(n.id) ? n.id : null);
        }}
        onPointerOut={() => onHover(null)}
        onClick={(e) => {
          e.stopPropagation();
          const n = pick(e);
          if (n && visible.has(n.id)) onSelect(n.id);
        }}
        onPointerMissed={() => onSelect(null)}
      >
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
    </group>
  );
}
