import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { particlePositions } from '../synthetic';

// Decorative only: one draw call for the whole field, no record behind any point, never selectable.
export function ParticleField({ count, reducedMotion }: { count: number; reducedMotion: boolean }) {
  const group = useRef<THREE.Group>(null);
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(particlePositions(count), 3));
    return g;
  }, [count]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  useFrame((_, delta) => {
    if (group.current && !reducedMotion) group.current.rotation.y += delta * 0.015;
  });
  return (
    <group ref={group}>
      <points geometry={geometry} raycast={() => null} frustumCulled={false}>
        <pointsMaterial color="#6f9bff" size={0.045} sizeAttenuation transparent opacity={0.55} depthWrite={false} blending={THREE.AdditiveBlending} />
      </points>
    </group>
  );
}
