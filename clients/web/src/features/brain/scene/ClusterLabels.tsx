import { Html } from '@react-three/drei';
import { CLUSTER_CENTER } from '../synthetic';
import { SOURCE_COLOR, SOURCE_LABEL, SOURCE_TYPES, type SourceType } from '../model';

export function ClusterLabels({ counts }: { counts: Record<SourceType, number> }) {
  return (
    <>
      {SOURCE_TYPES.map((t) => (
        <Html key={t} position={[CLUSTER_CENTER[t][0], CLUSTER_CENTER[t][1] + 2.4, CLUSTER_CENTER[t][2]]} center zIndexRange={[5, 0]} style={{ pointerEvents: 'none' }}>
          <span style={{ color: SOURCE_COLOR[t], font: '600 12px system-ui', letterSpacing: '0.06em', textShadow: '0 0 6px #000', whiteSpace: 'nowrap' }}>
            {`${SOURCE_LABEL[t].toUpperCase()} · ${counts[t]}`}
          </span>
        </Html>
      ))}
    </>
  );
}
