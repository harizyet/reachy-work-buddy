import { OrbitControls } from '@react-three/drei';
import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import * as THREE from 'three';

const HOME: [number, number, number] = [0, 2, 19];

// Orbit, zoom and pan with smooth damping; focusing a node eases the target toward it (instantly when motion is reduced);
// a reset token returns the view to where it began.
export function CameraRig({ focus, resetToken, reducedMotion }: { focus: [number, number, number] | null; resetToken: number; reducedMotion: boolean }) {
  const controls = useRef<{ target: THREE.Vector3; update(): void } | null>(null);
  const camera = useThree((s) => s.camera);
  const invalidate = useThree((s) => s.invalidate);
  const goal = useRef(new THREE.Vector3());

  useEffect(() => {
    camera.position.set(...HOME);
    goal.current.set(0, 0, 0);
    if (controls.current) {
      controls.current.target.set(0, 0, 0);
      controls.current.update();
    }
    invalidate();
  }, [resetToken, camera, invalidate]);

  useEffect(() => {
    if (!focus) return;
    goal.current.set(...focus);
    if (reducedMotion && controls.current) {
      controls.current.target.copy(goal.current);
      controls.current.update();
      invalidate();
    }
  }, [focus, reducedMotion, invalidate]);

  useFrame((_, delta) => {
    const c = controls.current;
    if (!c || reducedMotion) return;
    if (c.target.distanceToSquared(goal.current) > 0.0004) {
      c.target.lerp(goal.current, Math.min(1, delta * 4));
      c.update();
    }
  });

  return (
    <OrbitControls
      ref={controls as never}
      makeDefault
      enableDamping={!reducedMotion}
      dampingFactor={0.08}
      minDistance={5}
      maxDistance={40}
      rotateSpeed={0.6}
      zoomSpeed={0.7}
    />
  );
}
