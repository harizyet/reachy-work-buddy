import { Canvas } from '@react-three/fiber';
import { Bloom, EffectComposer } from '@react-three/postprocessing';
import { Html } from '@react-three/drei';
import { useEffect, useState } from 'react';
import { SOURCE_COLOR, type BrainEdge, type BrainNode, type SourceType } from './model';
import { CameraRig } from './scene/CameraRig';
import { ClusterLabels } from './scene/ClusterLabels';
import { ConnectionLines } from './scene/ConnectionLines';
import { KnowledgeNodes } from './scene/KnowledgeNodes';
import { ParticleField } from './scene/ParticleField';

export interface SceneProps {
  nodes: readonly BrainNode[];
  edges: readonly BrainEdge[];
  visible: ReadonlySet<string>;
  counts: Record<SourceType, number>;
  selectedId: string | null;
  particleCount: number;
  showAllLinks: boolean;
  /** A soft glow pass around bright points; costs extra full-screen passes. */
  bloom: boolean;
  reducedMotion: boolean;
  resetToken: number;
  onSelect(id: string | null): void;
}

// The 3D view. It stops rendering while the tab is hidden, renders on demand when motion is reduced, and gives its
// WebGL context back when it is removed.
export default function BrainScene(props: SceneProps) {
  const { nodes, edges, visible, counts, selectedId, particleCount, showAllLinks, bloom, reducedMotion, resetToken, onSelect } = props;
  const [hoveredId, setHovered] = useState<string | null>(null);
  const [hidden, setHidden] = useState(typeof document !== 'undefined' && document.hidden);
  useEffect(() => {
    const on = () => setHidden(document.hidden);
    document.addEventListener('visibilitychange', on);
    return () => document.removeEventListener('visibilitychange', on);
  }, []);

  const selected = nodes.find((n) => n.id === selectedId) ?? null;
  const hovered = nodes.find((n) => n.id === hoveredId) ?? null;
  return (
    <Canvas
      frameloop={hidden ? 'never' : reducedMotion ? 'demand' : 'always'}
      dpr={[1, 1.5]}
      gl={{ antialias: false, powerPreference: 'default', alpha: false }}
      camera={{ position: [0, 2, 19], fov: 55, near: 0.1, far: 120 }}
      style={{ background: '#05070d' }}
      onCreated={({ gl }) => {
        gl.setClearColor('#05070d');
      }}
    >
      <ParticleField count={particleCount} reducedMotion={reducedMotion} />
      <ConnectionLines nodes={nodes} edges={edges} selectedId={selectedId} showAll={showAllLinks} />
      <KnowledgeNodes bloom={bloom} nodes={nodes} visible={visible} selectedId={selectedId} hoveredId={hoveredId} onSelect={onSelect} onHover={setHovered} />
      <ClusterLabels counts={counts} />
      {hovered && hovered.id !== selectedId && (
        <Html position={[hovered.position[0], hovered.position[1] + 0.5, hovered.position[2]]} center zIndexRange={[10, 0]} style={{ pointerEvents: 'none' }}>
          <span style={{ color: '#fff', background: '#0b1224cc', border: `1px solid ${SOURCE_COLOR[hovered.type]}`, borderRadius: 4, padding: '2px 6px', font: '12px system-ui', whiteSpace: 'nowrap' }}>
            {hovered.title}
          </span>
        </Html>
      )}
      {bloom && (
        <EffectComposer multisampling={0}>
          <Bloom intensity={0.85} luminanceThreshold={0.2} luminanceSmoothing={0.25} mipmapBlur radius={0.65} />
        </EffectComposer>
      )}
      <CameraRig focus={selected ? selected.position : null} resetToken={resetToken} reducedMotion={reducedMotion} />
    </Canvas>
  );
}
