import { useBloom } from '../../app/displayPrefs';
import { Card } from '../../components/ui/Card';
import { Check } from './fields';

export function DisplayTab() {
  const [bloom, setBloom] = useBloom();
  return (
    <Card eyebrow="THIS BROWSER" title="Brain view">
      <p className="mb-3 text-sm">How the Brain page looks on this device. These choices are kept in this browser only and are never sent to Reachy.</p>
      <Check label="Glow effect (bloom)" checked={bloom} onChange={setBloom} />
      <p className="-mt-2 text-sm text-[var(--muted)]">
        Adds a soft glow around the bright points. It makes the picture richer but uses more of the graphics processor, so turn it off on a slower device or if the page feels sluggish. It starts off for people who prefer reduced motion.
      </p>
    </Card>
  );
}
