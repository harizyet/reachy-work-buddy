import { useNoteProcessing, useProcessingEnabled } from './useProcessing';

// Phase 49: a small mark on a note that Reachy has processed. It reads the same per-note status the panel does (shared cache), shows nothing for a note that was never sent or when
// the feature is off, and never says more than the server did: "processed" means a processing job finished for this note, not that anything was accepted.
const MARKS = {
  review_required: { glyph: '✨', label: 'Processed by Reachy: suggestions waiting for your review' },
  completed: { glyph: '✨', label: 'Processed by Reachy' },
  queued: { glyph: '⏳', label: 'Waiting to be processed by Reachy' },
  processing: { glyph: '⏳', label: 'Being processed by Reachy' },
  failed: { glyph: '⚠️', label: 'Reachy could not process this note' },
} as const;

export function ProcessedIcon({ noteId }: { noteId: string }) {
  const on = useProcessingEnabled().data === true;
  const state = useNoteProcessing(noteId, on).data?.state;
  if (!on || !state || state === 'not_processed') return null;
  const mark = MARKS[state];
  return (
    <span role="img" aria-label={mark.label} title={mark.label} className="ml-1 text-sm" data-testid="processed-icon" data-state={state}>
      {mark.glyph}
    </span>
  );
}
