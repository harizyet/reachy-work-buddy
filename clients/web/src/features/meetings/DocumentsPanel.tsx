import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, StaleSessionError } from '../../api/client';
import { uploadDocument } from '../../api/documents';
import type { Answer, FindingDto, Overview, RunState } from '../../api/meetingMultimodal';
import { Button } from '../../components/ui/Button';
import { StatusPill, type Tone } from '../../components/ui/StatusPill';
import { useDocuments } from '../documents/useDocuments';
import { formatTimestamp } from './format';
import { openSlide } from './SlideSuggestion';
import { useMultimodalActions, useOverview } from './useMeetingMultimodal';

// Phase 53. Documents attached to a meeting, the page estimates, questions across the transcript and the documents, and combined findings. A finding is a suggestion: an action becomes a task only
// when the owner confirms it here. A statement on a page is not evidence that the participants agreed with it, and which page was discussed is an estimate. All text is rendered as text.

const RUN_LABEL: Record<RunState, string> = { not_run: 'Not run', queued: 'Queued', processing: 'Working', succeeded: 'Done', failed: 'Failed' };
const RUN_TONE: Record<RunState, Tone> = { not_run: 'warn', queued: 'warn', processing: 'warn', succeeded: 'good', failed: 'bad' };
const FAILURE: Record<string, string> = {
  model_unavailable: 'The local model was not available.',
  bad_model_output: 'The model’s answer could not be used.',
  transcript_too_long: 'The transcript is too long to analyse.',
  timeout: 'It took too long.',
  source_changed: 'The transcript or a document changed while it was waiting. Run it again.',
  source_unavailable: 'A source is no longer available to you.',
  alignment_missing: 'The page estimates were not current. Estimate the pages first.',
  internal_error: 'Something went wrong.',
};
const KIND_LABEL: Record<FindingDto['kind'], string> = { discussion: 'Discussion points', decision: 'Decisions', disagreement: 'Where the pages and the discussion differ', open_question: 'Open questions', action: 'Actions to review' };
const DOC_STATE: Record<string, string> = { uploaded: 'Uploaded', queued: 'Queued', processing: 'Reading', ready: 'Ready', partial: 'Partly read', failed: 'Failed', deleting: 'Deleting' };
const message = (error: unknown): string | null => (error == null || error instanceof StaleSessionError ? null : error instanceof ApiError || error instanceof Error ? error.message : 'Something went wrong');
const isPowerPoint = (name: string) => /\.(pptx?|ppsx?|key|odp)$/i.test(name);

export function DocumentsPanel({ meetingId, onShow }: { meetingId: string; onShow: (seconds: number) => void }) {
  const query = useOverview(meetingId, true);
  const act = useMultimodalActions(meetingId);
  const data = query.data;
  if (query.isPending) return <p className="text-sm" role="status">Loading…</p>;
  if (!data) return <p role="alert" className="text-sm text-[var(--bad)]">{message(query.error) ?? 'Could not load the attached documents.'}</p>;
  const ready = data.documents.some((d) => d.ready);
  const aligning = ['queued', 'processing'].includes(data.alignment.state);
  const analysing = ['queued', 'processing'].includes(data.analysis.state);
  const error = [act.attach, act.detach, act.align, act.analyse, act.retry, act.confirm, act.dismiss].map((m) => message(m.error)).find(Boolean);

  return (
    <section aria-label="Attached documents" className="text-sm">
      <p className="text-xs text-[var(--muted)]">
        Attach a presentation or document to this meeting and Reachy will estimate which page was being discussed in each part of the transcript. It is an estimate from the words used; it cannot know what
        was on a screen. Nothing becomes a task until you confirm it. Presentations should be exported as PDF first.
      </p>
      <h3 className="mt-3 font-semibold">Attached documents</h3>
      {data.documents.length === 0 && <p className="mt-1 text-[var(--muted)]">Nothing is attached yet.</p>}
      <ul className="mt-1 space-y-1" aria-label="Attached documents list">
        {data.documents.map((d) => (
          <li key={d.document_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-[var(--border)] p-2">
            <span className="min-w-0 flex-1 break-words font-medium">{d.title}</span>
            <StatusPill tone={d.ready ? 'good' : d.state === 'failed' ? 'bad' : 'warn'}>{DOC_STATE[d.state] ?? d.state}</StatusPill>
            <span className="text-xs text-[var(--muted)]">{d.page_count ? `${d.page_count} page${d.page_count === 1 ? '' : 's'}` : 'pages not counted yet'}</span>
            <Link className="text-xs underline" to={`/documents/${encodeURIComponent(d.document_id)}`}>Open</Link>
            <Button variant="secondary" disabled={act.detach.isPending} onClick={() => act.detach.mutate(d.document_id)} aria-label={`Remove ${d.title} from this meeting`}>Remove</Button>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-xs text-[var(--muted)]">Removing a document here does not delete it; it only removes its page estimates and findings for this meeting.</p>
      <Attach meetingId={meetingId} attached={data.documents.map((d) => d.document_id)} onAttach={(id) => act.attach.mutate(id)} busy={act.attach.isPending} />

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button disabled={!ready || aligning || act.align.isPending} onClick={() => act.align.mutate(data.alignment.state === 'succeeded')}>{data.alignment.state === 'succeeded' ? 'Estimate the pages again' : 'Estimate the pages'}</Button>
        <StatusPill tone={RUN_TONE[data.alignment.state]}>{`Pages: ${RUN_LABEL[data.alignment.state]}`}</StatusPill>
        <Button variant="secondary" disabled={!ready || analysing || aligning || act.analyse.isPending} onClick={() => act.analyse.mutate(data.analysis.state === 'succeeded')}>Analyse with documents</Button>
        <StatusPill tone={RUN_TONE[data.analysis.state]}>{`Analysis: ${RUN_LABEL[data.analysis.state]}`}</StatusPill>
      </div>
      {!ready && data.documents.length > 0 && <p className="mt-1 text-xs text-[var(--muted)]">Waiting for an attached document to finish being read.</p>}
      {[data.alignment, data.analysis].map((r, i) => r.state === 'failed' && r.run && (
        <p key={i} role="alert" className="mt-2 text-[var(--bad)]">
          {FAILURE[r.run.error ?? ''] ?? 'It failed.'}{' '}
          <Button variant="secondary" onClick={() => r.run && act.retry.mutate(r.run.id)}>Retry</Button>
        </p>
      ))}
      {(data.alignment.transcript_changed || data.alignment.documents_changed || data.alignment.documents_added) && data.alignment.state !== 'not_run' && (
        <p className="mt-2 text-[var(--warn)]" role="status">The transcript or the documents changed since the pages were estimated. Estimate them again; your own decisions are kept and asked about again where they are affected.</p>
      )}
      {error && <p role="alert" className="mt-2 text-[var(--bad)]">{error}</p>}
      <PagesSummary data={data} />

      <Ask meetingId={meetingId} onShow={onShow} />
      <Findings data={data} onShow={onShow} busy={act.confirm.isPending || act.dismiss.isPending} onConfirm={(id, text) => act.confirm.mutate({ id, text })} onDismiss={(id) => act.dismiss.mutate(id)} />
    </section>
  );
}

function PagesSummary({ data }: { data: Overview }) {
  const estimated = data.windows.filter((w) => w.shown);
  if (data.alignment.state !== 'succeeded' && data.windows.length === 0) return null;
  const counts = { high: 0, medium: 0, low: 0, unknown: 0 };
  for (const w of data.windows) counts[w.suggestion?.certainty ?? 'unknown'] += 1;
  return (
    <div className="mt-3 text-xs text-[var(--muted)]" aria-label="Page estimates">
      <p>{`${estimated.length} of ${data.windows.length} parts of the transcript have a page shown (high ${counts.high}, medium ${counts.medium}, low ${counts.low}). The rest have no confident page; open the Transcript to read, confirm or correct them.`}</p>
      {data.unaddressed.length > 0 && (
        <details className="mt-1">
          <summary className="cursor-pointer">{`Pages with no discussion matched to them (${data.unaddressed.length})`}</summary>
          <p>This only means the wording of the discussion did not match them. It does not prove they were not shown.</p>
          <ul className="mt-1 flex flex-wrap gap-2">
            {data.unaddressed.slice(0, 80).map((u) => (
              <li key={`${u.document_id}:${u.page}`}><Link className="underline" to={openSlide(u.document_id, u.page)}>{`${data.documents.length > 1 ? u.document_title + ' ' : ''}p.${u.page}`}</Link></li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Attach({ meetingId, attached, onAttach, busy }: { meetingId: string; attached: string[]; onAttach: (id: string) => void; busy: boolean }) {
  const library = useDocuments(true);
  const [choice, setChoice] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState('');
  const [uploading, setUploading] = useState(false);
  const available = (library.data ?? []).filter((d) => !attached.includes(d.id) && d.state !== 'deleting');
  const act = useMultimodalActions(meetingId);

  async function upload() {
    if (!file) return;
    if (isPowerPoint(file.name)) return setNote('PowerPoint files are not read yet. Export the presentation as a PDF and upload that.');
    setUploading(true);
    setNote('');
    try {
      const doc = await uploadDocument({ file, sensitivity: 'work-private', processing_priority: 'normal' });
      await act.attach.mutateAsync(doc.id);
      setFile(null);
      setNote('Uploaded and attached. Reachy is reading it; you can estimate the pages when it shows Ready.');
    } catch (e) {
      setNote(message(e) ?? '');
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="mt-3 grid gap-3 rounded-md border border-dashed border-[var(--border)] p-2 sm:grid-cols-2">
      <div>
        <label className="block text-xs">
          Attach a document from your library
          <select aria-label="Document from your library" value={choice} onChange={(e) => setChoice(e.target.value)} className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-1">
            <option value="">Choose…</option>
            {available.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
          </select>
        </label>
        <Button className="mt-1" disabled={!choice || busy} onClick={() => { onAttach(choice); setChoice(''); }}>Attach</Button>
      </div>
      <div>
        <label className="block text-xs">
          Or upload one now (PDF, Word, image)
          <input aria-label="Upload a document" type="file" accept=".pdf,.docx,.png,.jpg,.jpeg,.ppt,.pptx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="mt-1 block w-full text-xs" />
        </label>
        <Button className="mt-1" variant="secondary" disabled={!file || uploading} onClick={() => void upload()}>{uploading ? 'Uploading…' : 'Upload and attach'}</Button>
        {note && <p role="status" className="mt-1 text-xs">{note}</p>}
      </div>
    </div>
  );
}

function Ask({ meetingId, onShow }: { meetingId: string; onShow: (seconds: number) => void }) {
  const act = useMultimodalActions(meetingId);
  const [question, setQuestion] = useState('');
  const answer = act.ask.data;
  return (
    <div className="mt-5" aria-label="Ask about this meeting and its documents">
      <h3 className="font-semibold">Ask across the meeting and its documents</h3>
      <form className="mt-1 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (question.trim().length >= 3) act.ask.mutate(question.trim()); }}>
        <input aria-label="Question" value={question} maxLength={500} placeholder="For example: what concerns were raised about slide 7?" onChange={(e) => setQuestion(e.target.value)} className="min-w-0 flex-1 rounded border border-[var(--border)] bg-[var(--bg)] p-1" />
        <Button type="submit" disabled={act.ask.isPending || question.trim().length < 3}>{act.ask.isPending ? 'Thinking…' : 'Ask'}</Button>
      </form>
      {message(act.ask.error) && <p role="alert" className="mt-1 text-[var(--bad)]">{message(act.ask.error)}</p>}
      {answer && <AnswerView answer={answer} onShow={onShow} />}
    </div>
  );
}

function AnswerView({ answer, onShow }: { answer: Answer; onShow: (seconds: number) => void }) {
  return (
    <div className="mt-2 rounded-md border border-[var(--border)] p-2" aria-label="Answer">
      {answer.message && <p>{answer.message}</p>}
      {answer.parts.map((p, i) => (
        <div key={i} className="mt-2">
          <p className="text-xs font-semibold uppercase text-[var(--muted)]">{p.label}</p>
          <p className="break-words">{p.text}</p>
          {p.note && <p className="text-xs text-[var(--warn)]">{p.note}</p>}
          <p className="mt-1 flex flex-wrap gap-2 text-xs">
            {p.cites.map((id) => {
              const c = answer.citations[id];
              if (!c) return null;
              return c.source === 'document' && c.document_id && c.page ? (
                <Link key={id} className="underline" to={openSlide(c.document_id, c.page)} title={c.excerpt}>{`[${id}] ${c.title ?? 'document'}, page ${c.page}`}</Link>
              ) : (
                <button key={id} type="button" className="underline" title={c.excerpt} onClick={() => onShow(c.start ?? 0)}>{`[${id}] transcript ${formatTimestamp(c.start)}${c.speaker ? `, ${c.speaker}` : ''}`}</button>
              );
            })}
          </p>
        </div>
      ))}
      {answer.possible_disagreements.map((d) => (
        <div key={d.window_key + d.slide_quote} className="mt-2 rounded border border-[var(--warn)] p-1 text-xs">
          <strong>Possible disagreement</strong> found when the pages were estimated:
          <blockquote className="border-l-2 border-[var(--border)] pl-2">The page says: “{d.slide_quote}”</blockquote>
          <blockquote className="border-l-2 border-[var(--border)] pl-2">It was said: “{d.spoken_quote}”</blockquote>
        </div>
      ))}
      {answer.associations.length > 0 && <p className="mt-2 text-xs text-[var(--muted)]">{answer.associations.map((a) => `${a.transcript} ↔ ${a.document}: ${a.meaning}`).join('; ')}</p>}
      {answer.caveats.map((c) => <p key={c} className="mt-1 text-xs text-[var(--muted)]">{c}</p>)}
      <p className="mt-1 text-xs text-[var(--muted)]">{`Class: ${answer.sensitivity}${answer.model ? ` · ${answer.model}` : ''} · ${(answer.latency_ms / 1000).toFixed(1)} s. Written by a model from machine-extracted text: check the citations.`}</p>
    </div>
  );
}

function Findings({ data, onShow, busy, onConfirm, onDismiss }: { data: Overview; onShow: (seconds: number) => void; busy: boolean; onConfirm: (id: string, text?: string) => void; onDismiss: (id: string) => void }) {
  const items = data.analysis.items.filter((i) => i.status !== 'dismissed');
  if (items.length === 0) return data.analysis.state === 'succeeded' ? <p className="mt-4 text-[var(--muted)]">Nothing in the meeting and its documents was clear enough to list.</p> : null;
  const kinds: FindingDto['kind'][] = ['action', 'decision', 'disagreement', 'open_question', 'discussion'];
  return (
    <div className="mt-5" aria-label="Combined findings">
      <h3 className="font-semibold">Combined findings <span className="text-xs font-normal text-[var(--muted)]">(written by a model; unverified)</span></h3>
      <p className="text-xs text-[var(--muted)]">Each quote was checked to be in the transcript or on the page it names. A decision, question or action needs spoken words. Nothing is added to your tasks until you confirm it.</p>
      {kinds.map((kind) => {
        const rows = items.filter((i) => i.kind === kind);
        if (rows.length === 0) return null;
        return (
          <div key={kind} className="mt-3">
            <h4 className="font-medium">{KIND_LABEL[kind]}</h4>
            <ul className="mt-1 space-y-2">
              {rows.map((i) => <Finding key={i.id} item={i} busy={busy} onShow={onShow} onConfirm={onConfirm} onDismiss={onDismiss} />)}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function Finding({ item: i, busy, onShow, onConfirm, onDismiss }: { item: FindingDto; busy: boolean; onShow: (seconds: number) => void; onConfirm: (id: string, text?: string) => void; onDismiss: (id: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(i.task_text ?? i.text);
  const action = i.kind === 'action' && (i.status === 'pending' || i.status === 'accepting');
  return (
    <li className="rounded-md bg-[var(--hover)] p-2">
      <p className="break-words">
        {i.support === 'uncertain' && i.kind !== 'discussion' && <span className="mr-2 rounded border border-[var(--warn)] px-1 text-xs text-[var(--warn)]" title="The quote is verified, but it may not support this summary">Check the quote</span>}
        <strong>{i.text}</strong>
        {i.assignee && <span className="ml-2 text-[var(--muted)]">{i.assignee}</span>}
        {i.stated_time && <span className="ml-2 text-[var(--muted)]">{i.stated_time}</span>}
        {i.status === 'accepted' && <span className="ml-2 text-xs">Added to your tasks</span>}
      </p>
      {i.evidence.map((c, n) => (
        <blockquote key={n} className="mt-1 border-l-2 border-[var(--border)] pl-2 text-[var(--muted)]">
          <span className="text-xs font-semibold">{c.source === 'transcript' ? 'Said: ' : 'The page says: '}</span>
          <span className="break-words">“{c.quote}”</span>
          <span className="block text-xs">
            {c.source === 'transcript' ? (
              <button type="button" className="underline" aria-label={`Play from ${formatTimestamp(c.start)}`} onClick={() => onShow(c.start ?? 0)}>{`${c.speaker ? c.speaker + ', ' : ''}${formatTimestamp(c.start)}`}</button>
            ) : c.document_id && c.page ? (
              <Link className="underline" to={openSlide(c.document_id, c.page)}>{`page ${c.page}`}</Link>
            ) : null}
          </span>
        </blockquote>
      ))}
      {(i.source_changed || i.document_changed) && <p className="text-xs text-[var(--warn)]">{i.source_changed ? 'The transcript has changed since this was found.' : 'The document has been read again since this was found.'}</p>}
      {i.ambiguity.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs">{i.ambiguity.map((a) => <li key={a}>{a}</li>)}</ul>}
      {action && (
        <>
          {editing ? <input aria-label="Task text" value={text} maxLength={300} onChange={(e) => setText(e.target.value)} className="mt-2 w-full rounded border border-[var(--border)] bg-[var(--bg)] p-1" /> : <p className="mt-1 text-xs text-[var(--muted)]">{`It would be added as: “${i.task_text ?? i.text}”`}</p>}
          <div className="mt-2 flex flex-wrap gap-2">
            <Button disabled={busy || (editing && !text.trim())} onClick={() => onConfirm(i.id, editing ? text : undefined)}>{editing ? 'Save and confirm' : 'Confirm as task'}</Button>
            {!editing && <Button variant="secondary" onClick={() => setEditing(true)}>Edit and confirm</Button>}
            <Button variant="secondary" disabled={busy} onClick={() => onDismiss(i.id)}>Dismiss</Button>
          </div>
        </>
      )}
      {!action && i.status !== 'accepted' && <Button variant="secondary" className="mt-1" disabled={busy} onClick={() => onDismiss(i.id)}>Dismiss</Button>}
    </li>
  );
}
