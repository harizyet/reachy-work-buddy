import { useState } from 'react';
import { ApiError, StaleSessionError } from '../../api/client';
import type { MeetingLinkDto, ProposalDto, ProcessingState } from '../../api/notepadProcessing';
import { Button } from '../../components/ui/Button';
import { useMeetingLinks, useNoteProcessing, useProcessingActions, useProcessingEnabled, useRecentMeetings } from './useProcessing';

// Phase 49. Everything below the note text: send the saved note to Reachy, see where it is, review what Reachy found, and tie the note to a recorded meeting.
// Reachy's findings are SUGGESTIONS until accepted; they are drawn apart from the owner's own tasks and reminders and say where their evidence came from.
// All note, proposal and meeting text is rendered as text.

const STATE_LABEL: Record<ProcessingState, string> = {
  not_processed: 'Not processed',
  queued: 'Queued',
  processing: 'Processing',
  review_required: 'Review required',
  completed: 'Completed',
  failed: 'Failed',
};
const KIND_LABEL = { task: 'Task', reminder: 'Reminder', event: 'Possible event (review only)', reference: 'Information' } as const;
const FROM_LABEL = { note: 'From the note', transcript: 'From a meeting transcript', both: 'From the note and a meeting transcript' } as const;
const FAILURE: Record<string, string> = {
  model_unavailable: 'The local model was not available.',
  bad_model_output: 'The model’s answer could not be used.',
  timeout: 'Processing took too long.',
  internal_error: 'Something went wrong.',
};
const WHEN = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

async function sha256(text: string): Promise<string | undefined> {
  try {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
  } catch {
    return undefined; // the guard is optional; the server still snapshots exactly what is stored
  }
}

const failure = (error: unknown): string | null =>
  error instanceof StaleSessionError ? null : error instanceof ApiError || error instanceof Error ? error.message : 'Something went wrong';

export function ProcessingPanel({ noteId, saveNow, currentId, currentText }: { noteId: string | null; saveNow: () => Promise<void>; currentId: () => string | null; currentText: () => string }) {
  const enabled = useProcessingEnabled();
  const on = enabled.data === true;
  const proc = useNoteProcessing(noteId, on);
  const linksQuery = useMeetingLinks(noteId, on);
  const act = useProcessingActions(noteId);
  const [checked, setChecked] = useState(false);
  const [withMeetings, setWithMeetings] = useState(false);
  const [message, setMessage] = useState('');
  if (!on) return null;

  const links = linksQuery.data ?? [];
  const confirmed = links.filter((l) => l.state === 'confirmed');
  const data = proc.data;
  const state = data?.state ?? 'not_processed';

  async function send(force: boolean) {
    setMessage('');
    await saveNow(); // the note is saved first; processing never waits for the model
    const id = currentId();
    if (!id) {
      setMessage('Write something first.');
      return;
    }
    try {
      await act.send.mutateAsync({ id, expected_hash: await sha256(currentText()), force, include_meetings: withMeetings });
    } catch (error) {
      setMessage(failure(error) ?? '');
    }
  }

  const open = (data?.proposals ?? []).filter((p) => p.status === 'pending' || p.status === 'accepting');
  const info = (data?.proposals ?? []).filter((p) => p.status === 'noted');
  const added = (data?.proposals ?? []).filter((p) => p.status === 'accepted');

  return (
    <section aria-label="Reachy processing" className="mt-3 border-t border-[var(--border)] pt-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={checked}
            disabled={act.send.isPending || state === 'queued' || state === 'processing'}
            onChange={(e) => {
              setChecked(e.target.checked);
              if (e.target.checked) void send(false).finally(() => setChecked(false));
            }}
          />
          Send to Reachy for processing
        </label>
        {confirmed.length > 0 && (
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={withMeetings} onChange={(e) => setWithMeetings(e.target.checked)} />
            Also use the linked meeting transcript{confirmed.length > 1 ? 's' : ''}
          </label>
        )}
        <span role="status" aria-label="Processing status" className="rounded-full border border-[var(--border)] px-2 py-0.5 text-xs">
          {data ? STATE_LABEL[state] : 'Checking…'}
        </span>
        {state === 'failed' && data?.job && (
          <>
            <span className="text-[var(--bad)]">{FAILURE[data.job.error ?? ''] ?? 'Processing failed.'}</span>
            <Button variant="secondary" onClick={() => data.job && act.retry.mutate(data.job.id)}>Retry</Button>
          </>
        )}
        {['review_required', 'completed'].includes(state) && (
          <Button variant="secondary" onClick={() => void send(true)}>Process again</Button>
        )}
      </div>
      {message && <p role="alert" className="mt-2 text-[var(--bad)]">{message}</p>}
      {failure(act.retry.error) && <p role="alert" className="mt-2 text-[var(--bad)]">{failure(act.retry.error)}</p>}
      {data?.note_changed_since_job && state !== 'not_processed' && (
        <p className="mt-2 text-[var(--muted)]">This note changed after it was last processed. The suggestions below come from the earlier text.</p>
      )}
      {data?.job?.meetings.filter((m) => !m.included).map((m) => (
        <p key={m.meeting_id} className="mt-2 text-[var(--muted)]">{`The transcript of “${m.title}” was not used: ${m.reason ?? 'unavailable'}. Process again once it is ready.`}</p>
      ))}

      {open.length > 0 && (
        <div className="mt-3 rounded-md border border-dashed border-[var(--border)] p-2" aria-label="Suggestions from Reachy">
          <h2 className="font-semibold">Suggestions from Reachy</h2>
          <p className="text-xs text-[var(--muted)]">Not yet confirmed. Nothing is added to your tasks or reminders until you accept it.</p>
          <ul className="mt-2 space-y-2">
            {open.map((p) => (
              <Proposal key={p.id} proposal={p} busy={act.accept.isPending || act.dismiss.isPending}
                onAccept={(body) => act.accept.mutate({ id: p.id, body })} onDismiss={() => act.dismiss.mutate(p.id)} />
            ))}
          </ul>
          {failure(act.accept.error) && <p role="alert" className="mt-2 text-[var(--bad)]">{failure(act.accept.error)}</p>}
        </div>
      )}
      {added.length > 0 && (
        <p className="mt-2 text-[var(--muted)]">
          Added from this note: {added.map((p) => (p.record_id ? `${KIND_LABEL[p.kind]} “${p.text}”` : `“${p.text}” (reviewed)`)).join('; ')}.
        </p>
      )}
      {info.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer">{`Information that stays in the note (${info.length})`}</summary>
          <ul className="mt-1 list-disc pl-5">{info.map((p) => <li key={p.id}>{p.text}</li>)}</ul>
        </details>
      )}

      <MeetingLinks links={links} busy={act.link.isPending} noteId={noteId}
        onLink={(meetingId, state) => act.link.mutate({ meetingId, state })} error={failure(act.link.error)} />
    </section>
  );
}

function Proposal({ proposal: p, busy, onAccept, onDismiss }: { proposal: ProposalDto; busy: boolean; onAccept: (body: { text?: string; kind?: 'task' | 'reminder' | 'event'; due_at?: string }) => void; onDismiss: () => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(p.text);
  const [kind, setKind] = useState<'task' | 'reminder' | 'event'>(p.kind === 'reference' ? 'task' : p.kind);
  const [due, setDue] = useState(p.due_at ? toLocalInput(p.due_at) : '');
  const needsTime = (editing ? kind : p.kind) === 'reminder' && !(editing ? due : p.due_at);
  const accept = () => {
    if (!editing) return onAccept({});
    onAccept({ text, kind, ...(kind === 'reminder' && due ? { due_at: new Date(due).toISOString() } : {}) });
  };
  return (
    <li className="rounded-md bg-[var(--hover)] p-2">
      <p>
        <span className="mr-2 rounded border border-[var(--border)] px-1 text-xs">{KIND_LABEL[p.kind]}</span>
        <strong className="break-words">{p.text}</strong>
        {p.kind === 'reminder' && p.due_at && <span className="ml-2 text-[var(--muted)]">{WHEN.format(new Date(p.due_at))}</span>}
      </p>
      {p.sources.map((s, i) => (
        <blockquote key={i} className="mt-1 border-l-2 border-[var(--border)] pl-2 text-[var(--muted)]">
          <span className="break-words">“{s.quote}”</span>
          <span className="block text-xs">{s.kind === 'note' ? 'Your note' : `Meeting “${s.title ?? 'meeting'}”${s.speaker ? `, ${s.speaker}` : ''}`}</span>
        </blockquote>
      ))}
      <p className="mt-1 text-xs text-[var(--muted)]">{FROM_LABEL[p.evidence_from]}</p>
      {p.source_changed && <p className="text-xs text-[var(--muted)]">The note has changed since this was found.</p>}
      {p.ambiguity.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-xs">{p.ambiguity.map((a) => <li key={a}>{a}</li>)}</ul>
      )}
      {editing && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input aria-label="Proposed text" value={text} maxLength={300} onChange={(e) => setText(e.target.value)} className="min-w-48 flex-1 rounded border border-[var(--border)] bg-[var(--bg)] p-1" />
          <select aria-label="Add as" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} className="rounded border border-[var(--border)] bg-[var(--bg)] p-1">
            <option value="task">Task</option>
            <option value="reminder">Reminder</option>
            <option value="event">Review only</option>
          </select>
          {kind === 'reminder' && <input aria-label="Reminder time" type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} className="rounded border border-[var(--border)] bg-[var(--bg)] p-1" />}
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        <Button disabled={busy || needsTime || (editing && !text.trim())} onClick={accept}>{editing ? 'Save and accept' : 'Accept'}</Button>
        {!editing && <Button variant="secondary" onClick={() => setEditing(true)}>Edit and accept</Button>}
        <Button variant="secondary" disabled={busy} onClick={onDismiss}>Dismiss</Button>
        {needsTime && <span className="self-center text-xs text-[var(--muted)]">Choose a time (Edit and accept) to add it as a reminder.</span>}
      </div>
    </li>
  );
}

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function MeetingLinks({ links, busy, noteId, onLink, error }: { links: MeetingLinkDto[]; busy: boolean; noteId: string | null; onLink: (meetingId: string, state: 'confirmed' | 'rejected') => void; error: string | null }) {
  const [picking, setPicking] = useState(false);
  const meetings = useRecentMeetings(picking);
  const linked = new Set(links.filter((l) => l.state === 'confirmed').map((l) => l.meeting_id));
  if (!noteId) return null;
  return (
    <div className="mt-3" aria-label="Meetings">
      {links.length > 0 && <h2 className="font-semibold">Meetings</h2>}
      <ul className="space-y-1">
        {links.map((l) => (
          <li key={l.id} className="flex flex-wrap items-center gap-2">
            <span className="break-words">
              {l.state === 'suggested' ? 'Taken during this meeting? ' : 'Linked to '}
              <strong>{l.meeting ? l.meeting.title : 'a meeting that was deleted'}</strong>
              {l.meeting?.started_at && <span className="text-[var(--muted)]">{` (${WHEN.format(new Date(l.meeting.started_at))})`}</span>}
              {l.meeting && !l.meeting.transcript_ready && <span className="text-[var(--muted)]"> · transcript not ready</span>}
            </span>
            {l.state === 'suggested' ? (
              <>
                <Button variant="secondary" disabled={busy} onClick={() => onLink(l.meeting_id, 'confirmed')}>Link</Button>
                <Button variant="secondary" disabled={busy} onClick={() => onLink(l.meeting_id, 'rejected')}>Not this meeting</Button>
              </>
            ) : (
              <Button variant="secondary" disabled={busy} onClick={() => onLink(l.meeting_id, 'rejected')}>Unlink</Button>
            )}
          </li>
        ))}
      </ul>
      {error && <p role="alert" className="mt-1 text-[var(--bad)]">{error}</p>}
      {!picking ? (
        <Button variant="secondary" className="mt-2" onClick={() => setPicking(true)}>Link to a meeting…</Button>
      ) : (
        <div className="mt-2 flex items-center gap-2">
          <select aria-label="Meeting to link" defaultValue="" className="rounded border border-[var(--border)] bg-[var(--bg)] p-1"
            onChange={(e) => { if (e.target.value) { onLink(e.target.value, 'confirmed'); setPicking(false); } }}>
            <option value="">{meetings.isPending ? 'Loading…' : 'Choose a meeting'}</option>
            {(meetings.data ?? []).filter((m) => !linked.has(m.id)).map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}
          </select>
          <Button variant="secondary" onClick={() => setPicking(false)}>Cancel</Button>
        </div>
      )}
    </div>
  );
}
