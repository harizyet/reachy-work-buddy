import { useState } from 'react';
import { ApiError, StaleSessionError } from '../../api/client';
import type { AnalysisState, EvidenceDto, ItemDto } from '../../api/meetingAnalysis';
import { Button } from '../../components/ui/Button';
import { formatTimestamp } from './format';
import { useAnalysisActions, useMeetingAnalysis } from './useMeetingAnalysis';

// Phase 31. What Reachy found in a finished meeting: decisions, open questions and action candidates, each with the transcript line it rests on.
// Reachy's findings are SUGGESTIONS: an action becomes a task only when the owner confirms it here. A model wrote them from a speech-to-text transcript, so each one shows its
// evidence and can be dismissed. All meeting and item text is rendered as text.

const STATE_LABEL: Record<AnalysisState, string> = {
  not_analysed: 'Not analysed',
  queued: 'Queued',
  processing: 'Analysing',
  review_required: 'Actions to review',
  completed: 'Done',
  failed: 'Failed',
};
const FAILURE: Record<string, string> = {
  model_unavailable: 'The local model was not available.',
  bad_model_output: 'The model’s answer could not be used.',
  transcript_too_long: 'The transcript is too long to analyse.',
  timeout: 'The analysis took too long.',
  internal_error: 'Something went wrong.',
};

const failure = (error: unknown): string | null =>
  error == null || error instanceof StaleSessionError ? null : error instanceof ApiError || error instanceof Error ? error.message : 'Something went wrong';

export function AnalysisPanel({ meetingId, onShow }: { meetingId: string; onShow: (seconds: number) => void }) {
  const query = useMeetingAnalysis(meetingId, true);
  const act = useAnalysisActions(meetingId);
  const data = query.data;
  const state = data?.state ?? 'not_analysed';
  const items = data?.items ?? [];
  const open = items.filter((i) => i.kind === 'action' && (i.status === 'pending' || i.status === 'accepting'));
  const added = items.filter((i) => i.kind === 'action' && i.status === 'accepted');
  const decisions = items.filter((i) => i.kind === 'decision' && i.status === 'noted');
  const questions = items.filter((i) => i.kind === 'open_question' && i.status === 'noted');
  const strong = (xs: ItemDto[]) => xs.filter((i) => i.support === 'stated');
  const weak = (xs: ItemDto[]) => xs.filter((i) => i.support !== 'stated');
  const busy = act.confirm.isPending || act.dismiss.isPending;
  const skipped = Object.entries(data?.run?.rejected ?? {}).reduce((n, [, v]) => n + v, 0);

  return (
    <section aria-label="Meeting analysis" className="text-sm">
      <div className="flex flex-wrap items-center gap-3">
        {query.isPending ? null : state === 'not_analysed' ? (
          <Button disabled={act.start.isPending} onClick={() => act.start.mutate(false)}>Analyse this meeting</Button>
        ) : (
          <Button variant="secondary" disabled={act.start.isPending || state === 'queued' || state === 'processing'} onClick={() => act.start.mutate(true)}>Analyse again</Button>
        )}
        <span role="status" aria-label="Analysis status" className="rounded-full border border-[var(--border)] px-2 py-0.5 text-xs">{query.isPending ? 'Checking…' : STATE_LABEL[state]}</span>
        {state === 'failed' && data?.run && (
          <>
            <span className="text-[var(--bad)]">{FAILURE[data.run.error ?? ''] ?? 'The analysis failed.'}</span>
            <Button variant="secondary" onClick={() => data.run && act.retry.mutate(data.run.id)}>Retry</Button>
          </>
        )}
      </div>
      {(failure(act.start.error) ?? failure(act.retry.error)) && <p role="alert" className="mt-2 text-[var(--bad)]">{failure(act.start.error) ?? failure(act.retry.error)}</p>}
      {state === 'not_analysed' && <p className="mt-2 text-[var(--muted)]">Reachy reads the transcript with the local model and lists decisions, open questions and actions. Nothing becomes a task until you confirm it.</p>}
      {data?.transcript_changed_since_run && state !== 'not_analysed' && (
        <p className="mt-2 text-[var(--muted)]">The transcript was edited after this analysis. Check the evidence below, or analyse again.</p>
      )}
      {data?.run?.status === 'succeeded' && skipped > 0 && (
        <p className="mt-2 text-xs text-[var(--muted)]">{`${skipped} suggestion${skipped === 1 ? ' was' : 's were'} left out because the transcript did not support ${skipped === 1 ? 'it' : 'them'}.`}</p>
      )}

      {items.length > 0 && (
        <p className="mt-2 text-xs text-[var(--muted)]">
          Everything here was written by a model from a speech-to-text transcript, so treat it as unverified. Each quote is checked to be in the transcript; whether it supports the finding is for you to judge.
          Findings whose quote does not show the usual wording are kept, but collapsed under “Weaker suggestions”.
        </p>
      )}
      {open.length > 0 && (
        <div className="mt-3 rounded-md border border-dashed border-[var(--border)] p-2" aria-label="Actions from this meeting">
          <h3 className="font-semibold">Actions to review</h3>
          <p className="text-xs text-[var(--muted)]">Unverified and not yet confirmed. Nothing is added to your tasks until you confirm it.</p>
          {strong(open).length === 0 && <p className="mt-2 text-[var(--muted)]">No clear promise or request was found.</p>}
          <ul className="mt-2 space-y-2">
            {strong(open).map((i) => (
              <Action key={i.id} item={i} busy={busy} onShow={onShow} onConfirm={(text) => act.confirm.mutate({ id: i.id, text })} onDismiss={() => act.dismiss.mutate(i.id)} />
            ))}
          </ul>
          {weak(open).length > 0 && (
            <details className="mt-2" aria-label="Weaker action suggestions">
              <summary className="cursor-pointer">{`Weaker suggestions (${weak(open).length})`}</summary>
              <ul className="mt-2 space-y-2">
                {weak(open).map((i) => (
                  <Action key={i.id} item={i} busy={busy} onShow={onShow} onConfirm={(text) => act.confirm.mutate({ id: i.id, text })} onDismiss={() => act.dismiss.mutate(i.id)} />
                ))}
              </ul>
            </details>
          )}
          {failure(act.confirm.error) && <p role="alert" className="mt-2 text-[var(--bad)]">{failure(act.confirm.error)}</p>}
        </div>
      )}
      {added.length > 0 && (
        <p className="mt-2 text-[var(--muted)]">{`Added to your tasks: ${added.map((i) => `“${i.task_text ?? i.text}”`).join('; ')}.`}</p>
      )}
      <Findings title="Decisions" items={decisions} busy={busy} onShow={onShow} onDismiss={(id) => act.dismiss.mutate(id)} />
      <Findings title="Open questions" items={questions} busy={busy} onShow={onShow} onDismiss={(id) => act.dismiss.mutate(id)} />
      {state === 'completed' && items.length === 0 && <p className="mt-2 text-[var(--muted)]">Nothing in this transcript was clear enough to list.</p>}
    </section>
  );
}

// The quote is always really in the transcript; that does not make the conclusion right. "Check the quote" marks the items whose quote lacks the usual wording or does not cover the summary.
function Check({ item }: { item: ItemDto }) {
  return item.support === 'uncertain' ? (
    <span className="mr-2 rounded border border-[var(--warn)] px-1 text-xs text-[var(--warn)]" title="The quote is in the transcript, but it may not support this summary">Check the quote</span>
  ) : null;
}

function Evidence({ evidence, onShow }: { evidence: EvidenceDto[]; onShow: (seconds: number) => void }) {
  return (
    <>
      {evidence.map((e) => (
        <blockquote key={e.segment} className="mt-1 border-l-2 border-[var(--border)] pl-2 text-[var(--muted)]">
          <span className="break-words">“{e.quote}”</span>
          <span className="block text-xs">
            {e.speaker ? `${e.speaker}, ` : ''}
            <button type="button" className="underline" aria-label={`Play from ${formatTimestamp(e.start)}`} onClick={() => onShow(e.start)}>{formatTimestamp(e.start)}</button>
            {e.in_gap ? ' · recorded in a stretch with no audio' : ''}
          </span>
        </blockquote>
      ))}
    </>
  );
}

function Action({ item: i, busy, onShow, onConfirm, onDismiss }: { item: ItemDto; busy: boolean; onShow: (seconds: number) => void; onConfirm: (text?: string) => void; onDismiss: () => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(i.task_text ?? i.text);
  return (
    <li className="rounded-md bg-[var(--hover)] p-2">
      <p>
        <span className="mr-2 rounded border border-[var(--border)] px-1 text-xs">Action</span>
        <Check item={i} />
        <strong className="break-words">{i.text}</strong>
        {i.assignee && <span className="ml-2 text-[var(--muted)]">{i.assignee}</span>}
        {i.stated_time && <span className="ml-2 text-[var(--muted)]">{i.stated_time}</span>}
      </p>
      <Evidence evidence={i.evidence} onShow={onShow} />
      {i.source_changed && <p className="text-xs text-[var(--muted)]">The transcript has changed since this was found.</p>}
      {i.ambiguity.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs">{i.ambiguity.map((a) => <li key={a}>{a}</li>)}</ul>}
      {editing ? (
        <div className="mt-2">
          <input aria-label="Task text" value={text} maxLength={300} onChange={(e) => setText(e.target.value)} className="w-full rounded border border-[var(--border)] bg-[var(--bg)] p-1" />
        </div>
      ) : (
        <p className="mt-1 text-xs text-[var(--muted)]">{`It would be added as: “${i.task_text ?? i.text}”`}</p>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        <Button disabled={busy || (editing && !text.trim())} onClick={() => onConfirm(editing ? text : undefined)}>{editing ? 'Save and confirm' : 'Confirm as task'}</Button>
        {!editing && <Button variant="secondary" onClick={() => setEditing(true)}>Edit and confirm</Button>}
        <Button variant="secondary" disabled={busy} onClick={onDismiss}>Dismiss</Button>
      </div>
    </li>
  );
}

function Findings({ title, items, busy, onShow, onDismiss }: { title: string; items: ItemDto[]; busy: boolean; onShow: (seconds: number) => void; onDismiss: (id: string) => void }) {
  if (items.length === 0) return null;
  const strong = items.filter((i) => i.support === 'stated');
  const weak = items.filter((i) => i.support !== 'stated');
  const row = (i: ItemDto) => (
    <li key={i.id} className="rounded-md bg-[var(--hover)] p-2">
      <p className="break-words"><Check item={i} />{i.text}</p>
      <Evidence evidence={i.evidence} onShow={onShow} />
      {i.ambiguity.length > 0 && i.support === 'uncertain' && <ul className="mt-1 list-disc pl-5 text-xs">{i.ambiguity.map((a) => <li key={a}>{a}</li>)}</ul>}
      {i.source_changed && <p className="text-xs text-[var(--muted)]">The transcript has changed since this was found.</p>}
      <Button variant="secondary" className="mt-1" disabled={busy} onClick={() => onDismiss(i.id)}>Dismiss</Button>
    </li>
  );
  return (
    <div className="mt-3" aria-label={title}>
      <h3 className="font-semibold">{title} <span className="text-xs font-normal text-[var(--muted)]">(unverified)</span></h3>
      <ul className="mt-1 space-y-2">{strong.map(row)}</ul>
      {weak.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer">{`Weaker suggestions (${weak.length})`}</summary>
          <ul className="mt-2 space-y-2">{weak.map(row)}</ul>
        </details>
      )}
    </div>
  );
}
