import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getPageImage } from '../../api/documents';
import type { AttachedDocument, Certainty, ReviewStatus, WindowDto } from '../../api/meetingMultimodal';
import { Button } from '../../components/ui/Button';
import { formatTimestamp } from './format';

// Phase 53. Which page of an attached document a stretch of the transcript was probably about. It is an ESTIMATE from the wording of the discussion, never a statement about what was on a screen,
// so it is worded as "likely", labelled with how well the evidence supports it, and always correctable. Everything from documents and the model is rendered as text.

export const CERTAINTY_LABEL: Record<Certainty, string> = { high: 'High', medium: 'Medium', low: 'Low', unknown: 'Unknown' };
const CERTAINTY_HELP: Record<Certainty, string> = {
  high: 'The discussion names the page, or shares many distinctive words with it and no other page competes.',
  medium: 'The wording matches this page clearly, but another page could also fit.',
  low: 'Weak or ambiguous: several pages are plausible.',
  unknown: 'No page matches closely enough.',
};
const STATUS_LABEL: Partial<Record<ReviewStatus, string>> = {
  confirmed: 'Confirmed by you',
  replaced: 'Chosen by you',
  no_slide: 'Marked by you as not about a slide',
  removed: 'Suggestion removed by you',
  needs_revalidation: 'Needs your confirmation again',
};

/** A page picture fetched with the signed-in session and shown through a temporary object URL (a plain <img src> would not carry the session). */
function usePageImage(documentId: string, page: number, enabled: boolean) {
  const query = useQuery({ queryKey: ['documents', 'page-image', documentId, page, 'thumb'], queryFn: ({ signal }) => getPageImage(documentId, page, undefined, signal), enabled, staleTime: 5 * 60_000, retry: false });
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!query.data) {
      setUrl(null);
      return;
    }
    const made = URL.createObjectURL(query.data);
    setUrl(made);
    return () => URL.revokeObjectURL(made);
  }, [query.data]);
  return url;
}

export const openSlide = (documentId: string, page: number) => `/documents/${encodeURIComponent(documentId)}?page=${page}`;

export interface SlideActions {
  documents: AttachedDocument[];
  busy: boolean;
  onReview: (windowKey: string, decision: 'confirmed' | 'replaced' | 'no_slide' | 'removed', target?: { document_id: string; page: number }) => void;
  onWithdraw: (windowKey: string) => void;
}

export function SlideSuggestion({ window: w, continued, actions }: { window: WindowDto; continued: boolean; actions: SlideActions }) {
  const [open, setOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const shown = w.shown;
  const s = w.suggestion;
  const image = usePageImage(shown?.document_id ?? '', shown?.page ?? 1, open && shown !== null);
  const status = STATUS_LABEL[w.review_status];
  const owner = shown?.authority === 'owner';
  const stale = w.stale || w.review_status === 'needs_revalidation';

  if (!shown) {
    if (w.review_status === 'no_slide' || w.review_status === 'removed') {
      return (
        <div className="mt-2 text-xs text-[var(--muted)]" data-window={w.window_key}>
          {status}. <button type="button" className="underline" onClick={() => actions.onWithdraw(w.window_key)}>Undo</button>
        </div>
      );
    }
    return (
      <div className="mt-2 text-xs text-[var(--muted)]" data-window={w.window_key}>
        {w.unchecked ? 'Not checked: the model’s answer for this part could not be used.' : 'No confident slide association.'}{' '}
        <button type="button" className="underline" aria-expanded={picking} onClick={() => setPicking((v) => !v)}>Choose a page</button>
        {picking && <PagePicker documents={actions.documents} disabled={actions.busy} onPick={(t) => { setPicking(false); actions.onReview(w.window_key, 'replaced', t); }} />}
      </div>
    );
  }

  // A Low estimate is a hint, not a result: one muted line, no box, no certainty badge, and it opens to the same details and corrections.
  const low = shown.authority === 'suggested' && shown.certainty === 'low' && !stale && !open;
  if (low) {
    return (
      <div className="mt-1 text-xs text-[var(--muted)]" data-window={w.window_key} data-certainty="low">
        Possibly page {shown.page}{shown.slide_title ? ` (${shown.slide_title})` : ''} · low certainty ·{' '}
        <button type="button" className="underline" aria-expanded={false} aria-label={`Details for slide ${shown.page} at ${formatTimestamp(w.start)}`} onClick={() => setOpen(true)}>Details</button>
      </div>
    );
  }

  if (continued && !open && !stale && w.review_status === 'suggested') {
    return (
      <div className="mt-1 text-xs text-[var(--muted)]" data-window={w.window_key}>
        ↳ still about page {shown.page}
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-md border border-[var(--border)] bg-[var(--hover)] p-2 text-sm" data-window={w.window_key}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span aria-hidden="true">▣</span>
        <span className="min-w-0 flex-1 break-words">
          <strong>{owner ? 'Slide' : 'Likely slide'} {shown.page}</strong>
          {shown.slide_title ? ` — ${shown.slide_title}` : ''}
          <span className="text-[var(--muted)]">{` · ${shown.document_title} · this part of the transcript, ${formatTimestamp(w.start)}–${formatTimestamp(w.end)}`}</span>
        </span>
        {shown.certainty && <span className="rounded border border-[var(--border)] px-1 text-xs" title={CERTAINTY_HELP[shown.certainty]}>{`Certainty: ${CERTAINTY_LABEL[shown.certainty]}`}</span>}
        {owner && <span className="rounded border border-[var(--accent)] px-1 text-xs">Confirmed by you</span>}
        {stale && <span className="rounded border border-[var(--warn)] px-1 text-xs text-[var(--warn)]">Out of date</span>}
        <button type="button" className="text-xs underline" aria-expanded={open} aria-label={`Details for slide ${shown.page} at ${formatTimestamp(w.start)}`} onClick={() => setOpen((v) => !v)}>{open ? 'Hide' : 'Details'}</button>
      </div>
      {open && (
        <div className="mt-2 space-y-2">
          {w.review_status === 'needs_revalidation' && <p role="status" className="text-xs text-[var(--warn)]">The transcript or the document changed after you decided. Confirm it again to keep it.</p>}
          {w.stale && w.review_status !== 'needs_revalidation' && <p role="status" className="text-xs text-[var(--warn)]">The transcript or the document changed since this was estimated. Estimate the pages again.</p>}
          {s && !owner && s.reason && <p className="text-xs">{s.reason}</p>}
          {s && s.method === 'explicit_reference' && s.explicit_refs.length > 0 && <p className="text-xs text-[var(--muted)]">{s.explicit_refs.join(' ')}</p>}
          {s?.model_note && <p className="text-xs text-[var(--muted)]">{`The model says: “${s.model_note}” (model-written)`}</p>}
          {s?.relation === 'contradicts' && s.contradictions.map((c) => (
            <div key={c.slide_quote} className="rounded border border-[var(--warn)] p-1 text-xs">
              <strong>Possible disagreement</strong> (the model&apos;s reading; compare the quotes):
              <blockquote className="border-l-2 border-[var(--border)] pl-2">The page says: “{c.slide_quote}”</blockquote>
              <blockquote className="border-l-2 border-[var(--border)] pl-2">It was said: “{c.spoken_quote}”</blockquote>
            </div>
          ))}
          {status && <p className="text-xs">{status}.</p>}
          {image && <img src={image} alt={`Page ${shown.page} of ${shown.document_title}`} className="max-h-40 rounded border border-[var(--border)]" />}
          <p className="text-xs text-[var(--muted)]">This is an estimate from what was said. It does not show what was on a screen.</p>
          {s && s.alternatives.length > 0 && !owner && (
            <div className="text-xs">
              Other pages that could fit:
              <ul className="mt-1 flex flex-wrap gap-2">
                {s.alternatives.map((a) => (
                  <li key={`${a.document_id}:${a.page}`}>
                    <Button variant="secondary" disabled={actions.busy} onClick={() => actions.onReview(w.window_key, 'replaced', { document_id: a.document_id, page: a.page })}>
                      {`Use page ${a.page}${a.title ? ` — ${a.title}` : ''}${actions.documents.length > 1 ? ` (${a.document_title})` : ''}`}
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Link className="rounded border border-[var(--border)] px-2 py-1 text-xs underline" to={openSlide(shown.document_id, shown.page)}>Open the page</Link>
            {(!owner || stale) && <Button disabled={actions.busy} onClick={() => actions.onReview(w.window_key, 'confirmed', { document_id: shown.document_id, page: shown.page })}>{w.review_status === 'needs_revalidation' ? 'Confirm again' : 'Confirm'}</Button>}
            <Button variant="secondary" aria-expanded={picking} onClick={() => setPicking((v) => !v)}>Choose another page</Button>
            <Button variant="secondary" disabled={actions.busy} onClick={() => actions.onReview(w.window_key, 'no_slide')}>Not about a slide</Button>
            {!owner && s && <Button variant="secondary" disabled={actions.busy} onClick={() => actions.onReview(w.window_key, 'removed')}>Remove</Button>}
            {w.owner && <Button variant="secondary" disabled={actions.busy} onClick={() => actions.onWithdraw(w.window_key)}>Withdraw my decision</Button>}
          </div>
          {picking && <PagePicker documents={actions.documents} disabled={actions.busy} onPick={(t) => { setPicking(false); actions.onReview(w.window_key, 'replaced', t); }} />}
        </div>
      )}
    </div>
  );
}

export function PagePicker({ documents, disabled, onPick }: { documents: AttachedDocument[]; disabled: boolean; onPick: (t: { document_id: string; page: number }) => void }) {
  const ready = documents.filter((d) => d.ready && d.page_count);
  const [doc, setDoc] = useState(ready[0]?.document_id ?? '');
  const [page, setPage] = useState(1);
  const chosen = ready.find((d) => d.document_id === doc);
  if (ready.length === 0) return <p className="mt-1 text-xs text-[var(--muted)]">No attached document is ready.</p>;
  return (
    <span className="mt-1 flex flex-wrap items-center gap-2">
      {ready.length > 1 && (
        <select aria-label="Document" value={doc} onChange={(e) => setDoc(e.target.value)} className="rounded border border-[var(--border)] bg-[var(--bg)] p-1 text-xs">
          {ready.map((d) => <option key={d.document_id} value={d.document_id}>{d.title}</option>)}
        </select>
      )}
      <input aria-label="Page number" type="number" min={1} max={chosen?.page_count ?? 1} value={page} onChange={(e) => setPage(Number(e.target.value) || 1)} className="w-20 rounded border border-[var(--border)] bg-[var(--bg)] p-1 text-xs" />
      <Button disabled={disabled || !chosen || page < 1 || page > (chosen.page_count ?? 0)} onClick={() => chosen && onPick({ document_id: chosen.document_id, page })}>Use this page</Button>
    </span>
  );
}
