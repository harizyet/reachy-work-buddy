import { useNoteProcessing, useProcessingEnabled } from './useProcessing';

// Phase 49: a small text tag on a note that Reachy has processed. It reads the same per-note status the panel does (shared cache), shows nothing for a note that was never sent or when
// the feature is off, and never says more than the server did: "Processed" means a processing job finished for this note, not that anything was accepted.
const TAGS = {
  review_required: { text: 'Processed · review', title: 'Processed by Reachy: suggestions are waiting for your review', tone: 'border-[var(--accent)]' },
  completed: { text: 'Processed', title: 'Processed by Reachy', tone: 'border-[var(--border)]' },
  queued: { text: 'Queued', title: 'Waiting to be processed by Reachy', tone: 'border-[var(--border)]' },
  processing: { text: 'Processing', title: 'Being processed by Reachy', tone: 'border-[var(--border)]' },
  failed: { text: 'Failed', title: 'Reachy could not process this note', tone: 'border-[var(--bad)] text-[var(--bad)]' },
} as const;

export function ProcessedTag({ noteId }: { noteId: string }) {
  const on = useProcessingEnabled().data === true;
  const state = useNoteProcessing(noteId, on).data?.state;
  if (!on || !state || state === 'not_processed') return null;
  const tag = TAGS[state];
  return (
    <span title={tag.title} data-testid="processed-tag" data-state={state} className={`ml-2 inline-block whitespace-nowrap rounded-full border px-2 py-0.5 align-middle text-xs font-normal ${tag.tone}`}>
      {tag.text}
    </span>
  );
}
