import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { StaleSessionError } from '../../api/client';
import type { Meeting } from '../../api/types';
import { EmptyState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Dialog } from '../../components/ui/Dialog';
import { Spinner } from '../../components/ui/Spinner';
import { useDeepReview } from './DeepReview';
import { MeetingDetail } from './MeetingDetail';
import { DELETABLE, TERMINAL, formatTimestamp, silentSeconds, statusLabel } from './format';
import { useCancelMeeting, useDeleteMeetings, useMeetingList, useUpload } from './useMeetings';
import { useRecorder } from './useRecorder';

export function MeetingsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const list = useMeetingList();
  const remove = useDeleteMeetings();
  const cancel = useCancelMeeting();
  const deep = useDeepReview();
  const [search, setSearch] = useState('');
  const [confirm, setConfirm] = useState<{ title: string; text: string; ids: string[] } | null>(null);

  useEffect(() => deep.resume(), []); // eslint-disable-line react-hooks/exhaustive-deps

  const meetings = list.data ?? [];
  const shown = meetings.filter((m) => m.title.toLowerCase().includes(search.trim().toLowerCase()));
  const failed = meetings.filter((m) => m.status === 'failed' || m.status === 'cancelled');
  const status = list.error && !(list.error instanceof StaleSessionError) ? list.error.message : list.data && meetings.length === 0 ? 'No meetings uploaded yet.' : '';
  const actionError = [remove, cancel].map((m) => m.error).find((e) => e && !(e instanceof StaleSessionError));

  function askDelete(m: Meeting) {
    setConfirm({
      title: 'Delete this meeting?',
      text: `“${m.title}” will be removed with its recording, transcript, speaker names, corrections, summary and minutes. This cannot be undone.`,
      ids: [m.id],
    });
  }

  return (
    <div className="grid gap-4 md:grid-cols-[18rem_1fr]">
      <aside aria-label="Meeting records" className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
        <Button className="w-full" onClick={() => navigate('/meetings')}>
          ＋ Add meeting
        </Button>
        <div className="mt-3 flex items-center justify-between">
          <h2 className="font-semibold">Meeting records</h2>
          <Button variant="secondary" aria-label="Refresh meeting records" onClick={() => void list.refetch()}>
            ↻
          </Button>
        </div>
        <label className="mt-1 block text-sm">
          Find a meeting
          <input
            type="search"
            placeholder="Search titles…"
            className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        {failed.length > 0 && (
          <Button
            variant="secondary"
            className="mt-2 w-full"
            onClick={() =>
              setConfirm({
                title: 'Delete failed and cancelled meetings?',
                text: `This removes ${failed.length} meeting${failed.length === 1 ? '' : 's'} and ${failed.length === 1 ? 'its' : 'their'} recording${failed.length === 1 ? '' : 's'}. It cannot be undone.`,
                ids: failed.map((m) => m.id),
              })
            }
          >
            {`Delete failed and cancelled (${failed.length})`}
          </Button>
        )}
        <p role="status" className="min-h-5 text-sm text-[var(--bad)]">
          {actionError?.message ?? status}
        </p>
        {list.isPending && <Spinner label="Loading meetings" />}
        <ul className="divide-y divide-[var(--border)]">
          {shown.map((m) => (
            <li key={m.id} className={`py-2 ${m.id === id ? 'bg-[var(--hover)]' : ''}`}>
              <div className="flex items-start justify-between gap-2">
                <strong className="break-words">
                  {m.title}
                  {silentSeconds(m) > 0 && <span role="img" aria-label="Part of this recording has no audio" title="Part of this recording has no audio"> ⚠</span>}
                </strong>
                <span className="shrink-0 text-xs text-[var(--muted)]">{statusLabel(m.status)}</span>
              </div>
              {m.description && <p className="break-words text-sm">{m.description}</p>}
              <p className="text-xs text-[var(--muted)]">{`Uploaded ${new Date(m.created_at).toLocaleString()}`}</p>
              <div className="mt-1 flex flex-wrap gap-1">
                <Link
                  to={`/meetings/${encodeURIComponent(m.id)}`}
                  aria-pressed={m.id === id}
                  className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--hover)]"
                >
                  View details
                </Link>
                {DELETABLE.includes(m.status) && (
                  <Button variant="secondary" aria-label={`Delete ${m.title}`} onClick={() => askDelete(m)}>
                    Delete
                  </Button>
                )}
                {!TERMINAL.includes(m.status) && (
                  <Button variant="secondary" onClick={() => cancel.mutate(m.id)}>
                    Cancel processing
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
        {list.data && shown.length === 0 && meetings.length > 0 && <EmptyState>No matching meetings.</EmptyState>}
      </aside>

      <div className="min-w-0">
        {id ? (
          <MeetingDetail
            key={id}
            id={id}
            onClose={() => navigate('/meetings')}
            onDelete={askDelete}
          />
        ) : (
          <CreateMeeting />
        )}
      </div>

      <Dialog open={confirm !== null} title={confirm?.title ?? 'Confirm'} onClose={() => setConfirm(null)}>
        <h2 className="text-lg font-semibold">{confirm?.title}</h2>
        <p className="my-3 break-words text-sm">{confirm?.text}</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirm(null)}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              const ids = confirm?.ids ?? [];
              setConfirm(null);
              remove.mutate(ids);
              if (id && ids.includes(id)) navigate('/meetings');
            }}
          >
            Delete
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

function CreateMeeting() {
  const upload = useUpload();
  const recorder = useRecorder();
  const fileRef = useRef<HTMLInputElement>(null);
  const [fields, setFields] = useState({ title: '', project: '', participants: '', context: '' });
  const [message, setMessage] = useState('');
  const set = (key: keyof typeof fields) => (e: { target: { value: string } }) => setFields({ ...fields, [key]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const file = fileRef.current?.files?.[0];
    const source: Blob | undefined = recorder.clip?.blob ?? file;
    if (!source) {
      setMessage('Record a clip or choose a recording to upload');
      return;
    }
    const form = new FormData();
    form.set('title', fields.title);
    form.set('project_scope', fields.project);
    form.set('participants', fields.participants);
    form.set('context', fields.context);
    form.set('audio', source, recorder.clip ? `recording.${recorder.extension}` : (file as File).name);
    setMessage('Uploading…');
    try {
      await upload.mutateAsync(form);
      setMessage('Uploaded.');
      setFields({ title: '', project: '', participants: '', context: '' });
      if (fileRef.current) fileRef.current.value = '';
      recorder.discard();
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setMessage(e instanceof Error ? e.message : 'Upload failed');
    }
  }

  const input = 'mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2';
  return (
    <Card eyebrow="RECORDINGS" title="Add a meeting">
      <p className="mb-3 text-sm">
        Record or upload a meeting to transcribe it and detect speakers locally. Recordings and transcripts stay in your homelab. You can view the transcript and speaker timings separately.
      </p>
      {recorder.supported ? (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {!recorder.recording && <Button onClick={() => void recorder.start()}>Start recording</Button>}
          {recorder.recording && (
            <Button variant="secondary" onClick={recorder.stop}>
              Stop recording
            </Button>
          )}
          {recorder.clip && (
            <Button variant="secondary" onClick={recorder.discard}>
              Discard recording
            </Button>
          )}
          <span role="status" className="text-sm text-[var(--muted)]">
            {recorder.error ||
              (recorder.recording
                ? `Recording… ${formatTimestamp(recorder.elapsed)}`
                : recorder.clip
                  ? `Recorded clip ready (${formatTimestamp(recorder.clip.seconds)}).`
                  : '')}
          </span>
        </div>
      ) : (
        <p role="status" className="mb-3 text-sm text-[var(--muted)]">
          Recording from the browser is not supported here — upload a file instead.
        </p>
      )}
      <form onSubmit={(e) => void submit(e)}>
        <label className="mb-2 block text-sm">
          Title
          <input className={input} required maxLength={256} value={fields.title} onChange={set('title')} />
        </label>
        <label className="mb-2 block text-sm">
          Project (optional)
          <input className={input} maxLength={256} value={fields.project} onChange={set('project')} />
        </label>
        <label className="mb-2 block text-sm">
          Participants (optional, comma-separated)
          <input className={input} maxLength={1024} placeholder="Hariz, Alice" value={fields.participants} onChange={set('participants')} />
        </label>
        <label className="mb-2 block text-sm">
          Context (optional)
          <textarea className={input} rows={2} maxLength={4096} value={fields.context} onChange={set('context')} />
        </label>
        <label className="mb-3 block text-sm">
          Recording file (skip if you recorded a clip above)
          <input
            ref={fileRef}
            type="file"
            disabled={recorder.clip !== null}
            accept="audio/wav,audio/flac,audio/x-flac,audio/mp4,audio/mpeg,audio/opus,audio/webm,.wav,.flac,.m4a,.aac,.mp3,.opus,.webm"
            className="mt-1 block w-full"
          />
        </label>
        <Button type="submit" disabled={upload.isPending}>
          Upload meeting
        </Button>
      </form>
      <p role="status" className="mt-2 text-sm">
        {message}
      </p>
    </Card>
  );
}

