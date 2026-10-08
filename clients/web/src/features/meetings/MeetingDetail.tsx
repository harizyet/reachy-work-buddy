import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { StaleSessionError } from '../../api/client';
import {
  clearOutput,
  correctLine,
  deepInfo,
  describeMeeting,
  meetingAudioUrl,
  renameSpeaker,
  replaceText,
  revertLine,
  setTitle,
  startDeepReview,
  suggestCorrections,
  writeOutput,
} from '../../api/meetings';
import type { DeepInfo, Meeting, Suggestion, SuggestionResult } from '../../api/types';
import { ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Dialog } from '../../components/ui/Dialog';
import { Spinner } from '../../components/ui/Spinner';
import { useChat } from '../chat/ChatProvider';
import { useDeepReview } from './DeepReview';
import { DELETABLE, READY, TIER_LABEL, formatTimestamp, silentSeconds, silentSummary, speakerName, statusDescription, statusLabel } from './format';
import { useAcceptMeeting, useMeeting } from './useMeetings';

type Section = 'transcript' | 'summary' | 'minutes';
type Task = 'corrections' | 'summary' | 'minutes';

const messageOf = (error: unknown) => (error instanceof Error ? error.message : 'Something went wrong');

export function MeetingDetail({ id, onClose, onDelete }: { id: string; onClose: () => void; onDelete: (m: Meeting) => void }) {
  const query = useMeeting(id);
  const accept = useAcceptMeeting();
  const chat = useChat();
  const navigate = useNavigate();
  const deep = useDeepReview();
  const [section, setSection] = useState<Section>('transcript');
  const [status, setStatus] = useState('');
  const [outputStatus, setOutputStatus] = useState('');
  const [generating, setGenerating] = useState<'summary' | 'minutes' | null>(null);
  const [outputModel, setOutputModel] = useState('local');
  const [titleOpen, setTitleOpen] = useState(false);
  const [speakerFor, setSpeakerFor] = useState<string | null>(null);
  const [lineFor, setLineFor] = useState<number | null>(null);
  const [deepTask, setDeepTask] = useState<{ task: Task; info: DeepInfo } | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [suggestStatus, setSuggestStatus] = useState('');
  const [suggestModel, setSuggestModel] = useState('local');
  const [playing, setPlaying] = useState(-1);
  const player = useRef<HTMLAudioElement>(null);
  const meeting = query.data;

  // A review that finished while this meeting is open delivers its result here.
  const job = deep.job;
  const handled = useRef<string | null>(null);
  useEffect(() => {
    if (!job || job.meeting_id !== id || job.status !== 'done' || handled.current === job.id) return;
    handled.current = job.id;
    if (!job.task || job.task === 'corrections') {
      if (job.result) showResult(job.result);
    } else void query.refetch();
  }); // eslint-disable-line react-hooks/exhaustive-deps

  if (query.isPending) return <Spinner label="Loading" />;
  if (!meeting) return <ErrorState message={query.error?.message ?? 'Meeting not found'} onRetry={() => void query.refetch()} />;

  const m = meeting;
  const ready = Boolean(m.transcript_segments?.length) && READY.includes(m.status);
  const shownSection: Section = ready ? section : 'transcript';

  function showResult(result: SuggestionResult) {
    setSuggestions(result.suggestions);
    const used = result.terms_used;
    setSuggestStatus(
      result.truncated
        ? 'Some parts of the meeting could not be checked. Run again to retry.'
        : result.suggestions.length
          ? `Checked against ${used} term${used === 1 ? '' : 's'}.`
          : used
            ? `No likely mistakes found (checked against ${used} terms).`
            : 'No likely mistakes found. Add key terms to catch more.',
    );
  }

  async function run(kind: 'summary' | 'minutes', model: string) {
    if (model === 'deep') return void askDeep(kind);
    setGenerating(kind);
    setOutputStatus('');
    try {
      accept(await writeOutput(id, kind, model));
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setOutputStatus(messageOf(e));
    } finally {
      setGenerating(null);
    }
  }

  function pick(next: Section) {
    setSection(next);
    // The first look at a summary or minutes that does not exist yet writes it with the local model.
    if ((next === 'summary' || next === 'minutes') && !m[next] && generating === null) void run(next, 'local');
  }

  async function askDeep(task: Task) {
    const setMsg = task === 'corrections' ? setSuggestStatus : setOutputStatus;
    try {
      const info = await deepInfo();
      if (!info.available) return setMsg(`Deep local is unavailable: ${info.reason || 'not ready'}.`);
      setDeepTask({ task, info });
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setMsg(messageOf(e));
    }
  }

  async function beginDeep() {
    const pending = deepTask;
    setDeepTask(null);
    if (!pending) return;
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      try {
        await Notification.requestPermission();
      } catch {
        // Notifications are optional.
      }
    }
    const setMsg = pending.task === 'corrections' ? setSuggestStatus : setOutputStatus;
    try {
      const started = await startDeepReview(id, pending.task);
      setMsg(`Deep ${pending.task === 'corrections' ? 'review' : pending.task} started. Reachy is unavailable until it finishes.`);
      if (pending.task === 'corrections') setSuggestions([]);
      deep.follow(started.id);
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setMsg(messageOf(e));
    }
  }

  async function suggest() {
    if (suggestModel === 'deep') return void askDeep('corrections');
    setSuggestStatus('Checking…');
    try {
      showResult(await suggestCorrections(id, suggestModel));
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setSuggestStatus(messageOf(e));
    }
  }

  const groups = [...suggestions.reduce((acc, s) => {
    const key = `${s.original}\u0000${s.suggested}`;
    acc.set(key, { ...s, places: (acc.get(key)?.places ?? 0) + 1 });
    return acc;
  }, new Map<string, Suggestion & { places: number }>()).values()];

  const playFrom = (seconds: number) => {
    const audio = player.current;
    if (!audio) return;
    audio.currentTime = Math.max(0, seconds);
    void audio.play?.()?.catch?.(() => undefined); // some browsers want a user gesture; the controls still work
  };

  const segments = m.transcript_segments ?? [];
  const aligned = m.aligned_speakers && m.aligned_speakers.length === segments.length ? m.aligned_speakers : null;
  const output = shownSection === 'summary' || shownSection === 'minutes' ? m[shownSection] : null;

  return (
    <Card title={m.title}>
      <div className="-mt-9 mb-3 flex justify-end gap-2">
        <Button variant="secondary" onClick={() => setTitleOpen(true)}>
          Edit title
        </Button>
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
      </div>
      {m.description && <p className="mb-1 break-words text-sm italic">{m.description}</p>}
      <p className="text-sm text-[var(--muted)]">
        {[
          `Status: ${statusLabel(m.status)}`,
          m.project_scope ? `Project: ${m.project_scope}` : '',
          m.participants.length ? `Participants: ${m.participants.join(', ')}` : '',
          m.duration_seconds ? `Duration: ${formatTimestamp(m.duration_seconds)}` : '',
        ]
          .filter(Boolean)
          .join(' · ')}
      </p>
      {m.context && <p className="break-words text-sm">{m.context}</p>}
      {silentSeconds(m) > 0 && (
        <p role="status" className="my-2 rounded border border-[var(--warn)] bg-[var(--warn-bg)] p-2 text-sm text-[var(--warn)]">{`⚠ ${silentSummary(m)}`}</p>
      )}
      <p role="status" className="text-sm">{status || statusDescription(m)}</p>
      {m.error_detail && (
        <details className="my-2">
          <summary>Technical error</summary>
          <pre className="whitespace-pre-wrap break-words text-xs">{m.error_detail}</pre>
        </details>
      )}

      {ready && (
        <div role="group" aria-label="What to do with this meeting" className="my-3 flex flex-wrap gap-2">
          {(['summary', 'minutes', 'transcript'] as const).map((name) => (
            <Button key={name} variant="secondary" aria-pressed={shownSection === name} className={shownSection === name ? 'ring-2 ring-[var(--accent)]' : ''} onClick={() => pick(name)}>
              {name[0]!.toUpperCase() + name.slice(1)}
            </Button>
          ))}
          <Button
            variant="secondary"
            onClick={() => {
              chat.setContext({ id: m.id, title: m.title });
              navigate('/chat');
            }}
          >
            Use as context
          </Button>
          {DELETABLE.includes(m.status) && (
            <Button variant="secondary" onClick={() => onDelete(m)}>
              Delete meeting
            </Button>
          )}
        </div>
      )}
      {!ready && DELETABLE.includes(m.status) && (
        <Button variant="secondary" onClick={() => onDelete(m)}>
          Delete meeting
        </Button>
      )}

      {ready && (shownSection === 'summary' || shownSection === 'minutes') && (
        <div>
          <p role="status" className="text-sm">
            {generating === shownSection ? `Writing the ${shownSection} with the local model…` : outputStatus || (output ? '' : `No ${shownSection} yet.`)}
          </p>
          <div className="whitespace-pre-wrap break-words">{generating === shownSection ? '' : (output?.text ?? '')}</div>
          {output && generating !== shownSection && (
            <p className="text-sm text-[var(--muted)]">
              {`Written by ${TIER_LABEL[output.tier] ?? output.tier}${output.generated_at ? ' · ' + new Date(output.generated_at).toLocaleString() : ''}. A model wrote this from a speech-to-text transcript, so check it; if it is not accurate enough, rerun it on a stronger model.`}
            </p>
          )}
          <label className="mt-2 block text-sm">
            Rerun with{' '}
            <select className="rounded border border-[var(--border)] bg-[var(--bg)] p-1" value={outputModel} onChange={(e) => setOutputModel(e.target.value)}>
              <option value="local">Local: private and quick</option>
              <option value="deep">Deep local: larger model, Reachy unavailable while it runs</option>
              <option value="cloud">Cloud: sends the transcript text to your cloud provider</option>
            </select>
          </label>
          <div className="mt-2 flex gap-2">
            <Button disabled={generating !== null} onClick={() => void run(shownSection, outputModel)}>
              {output ? 'Rerun' : `Write the ${shownSection}`}
            </Button>
            {output && (
              <Button
                variant="secondary"
                onClick={() =>
                  void clearOutput(id, shownSection)
                    .then(accept)
                    .catch((e: unknown) => !(e instanceof StaleSessionError) && setOutputStatus(messageOf(e)))
                }
              >
                Clear
              </Button>
            )}
          </div>
        </div>
      )}

      {shownSection === 'transcript' && (
        <div>
          {segments.length > 0 && (
            <div className="my-3 rounded border border-[var(--border)] p-2">
              <h4 className="font-medium">Suggest corrections</h4>
              <label className="block text-sm">
                Model{' '}
                <select className="rounded border border-[var(--border)] bg-[var(--bg)] p-1" value={suggestModel} onChange={(e) => setSuggestModel(e.target.value)}>
                  <option value="local">Local: private and quick</option>
                  <option value="deep">Deep local: larger model, Reachy unavailable while it runs</option>
                  <option value="cloud">Cloud: sends the transcript text to your cloud provider</option>
                </select>
              </label>
              <Button className="mt-2" disabled={deep.unavailable} onClick={() => void suggest()}>
                Suggest corrections
              </Button>
              <p role="status" className="text-sm">{suggestStatus}</p>
              <ul className="divide-y divide-[var(--border)]">
                {groups.map((g) => (
                  <li key={`${g.original}\u0000${g.suggested}`} className="flex flex-wrap items-center gap-2 py-2">
                    <span className="min-w-0 flex-1 break-words">
                      <strong>{`${g.original} → ${g.suggested}`}</strong>
                      <span className="block text-xs text-[var(--muted)]">
                        {({ high: 'High confidence: same letters as your term', likely: 'Matches your term: judged by the model, check it' } as Record<string, string>)[g.confidence] ?? 'Model guess: check before applying'}
                      </span>
                      <span className="block text-sm">{g.reason}</span>
                    </span>
                    <Button
                      onClick={() =>
                        void replaceText(id, g.original, g.suggested)
                          .then(async (result) => {
                            setSuggestions((all) => all.filter((s) => !(s.original === g.original && s.suggested === g.suggested)));
                            setSuggestStatus(`Changed ${result.replaced_segments} place${result.replaced_segments === 1 ? '' : 's'}.`);
                            await query.refetch();
                          })
                          .catch((e: unknown) => !(e instanceof StaleSessionError) && setSuggestStatus(messageOf(e)))
                      }
                    >
                      {g.places > 1 ? `Change all ${g.places}` : 'Change'}
                    </Button>
                    <Button variant="secondary" onClick={() => setSuggestions((all) => all.filter((s) => !(s.original === g.original && s.suggested === g.suggested)))}>
                      Dismiss
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <h4 className="mt-3 font-medium">Recording</h4>
          <audio
            ref={player}
            controls
            preload="none"
            src={meetingAudioUrl(id)}
            className="w-full"
            onTimeUpdate={(e) => {
              const now = e.currentTarget.currentTime;
              setPlaying(segments.findIndex((s) => now >= s.start && now < s.end));
            }}
          />
          <p className="text-sm text-[var(--muted)]">Select a transcript line to play from its start; use Edit on a line to fix it by hand.</p>
          <h4 className="mt-3 font-medium">Transcript</h4>
          {segments.length === 0 && <p className="text-sm text-[var(--muted)]">No transcript yet.</p>}
          <ul>
            {segments.map((segment, index) => {
              const label = aligned?.[index] ?? null;
              const previous = aligned && index > 0 ? aligned[index - 1] : null;
              const corrected = m.transcript_corrections[String(index)];
              return (
                <li key={index} data-index={index} className={`py-1 ${playing === index ? 'bg-[var(--hover)]' : ''}`}>
                  {m.audio_gaps?.segments.includes(index) && (
                    <span role="img" aria-label="No audio was recorded for most of this line" title="No audio was recorded for most of this line">⚠ </span>
                  )}
                  {label && label !== previous && (
                    <Button variant="secondary" aria-label={`Rename ${speakerName(m, label)}`} className="mr-1" onClick={() => setSpeakerFor(label)}>
                      {speakerName(m, label)}
                    </Button>
                  )}
                  <span
                    role="button"
                    tabIndex={0}
                    title="Play from here"
                    className="cursor-pointer break-words"
                    onClick={() => playFrom(segment.start)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        playFrom(segment.start);
                      }
                    }}
                  >
                    {`${formatTimestamp(segment.start)}–${formatTimestamp(segment.end)}  ${corrected ?? segment.text}${corrected !== undefined ? '  (edited)' : ''}`}
                  </span>{' '}
                  <Button variant="secondary" aria-label={`Edit line at ${formatTimestamp(segment.start)}`} onClick={() => setLineFor(index)}>
                    Edit
                  </Button>
                </li>
              );
            })}
          </ul>
          <h4 className="mt-3 font-medium">Raw speaker segments</h4>
          {!m.diarization_segments?.length && <p className="text-sm text-[var(--muted)]">No speaker segments yet.</p>}
          <ul>
            {(m.diarization_segments ?? []).map((s, i) => (
              <li key={i} className="text-sm">{`${formatTimestamp(s.start)}–${formatTimestamp(s.end)}  ${s.speaker || 'unknown speaker'}`}</li>
            ))}
          </ul>
        </div>
      )}

      <TitleDialog open={titleOpen} meeting={m} onClose={() => setTitleOpen(false)} onSaved={accept} />
      <SpeakerDialog label={speakerFor} meeting={m} onClose={() => setSpeakerFor(null)} onSaved={accept} onError={setStatus} />
      <LineDialog index={lineFor} meeting={m} onClose={() => setLineFor(null)} onSaved={accept} onError={setStatus} />
      <Dialog open={deepTask !== null} title="Reachy will be unavailable" onClose={() => setDeepTask(null)}>
        <h2 className="text-lg font-semibold">Reachy will be unavailable</h2>
        <p className="my-3 text-sm">
          {`Reachy will be unavailable for about ${Math.max(1, Math.round((deepTask?.info.eta_seconds ?? 330) / 60))} minutes. The larger model takes over the GPU: it loads (about 2 minutes), works on this meeting, then Reachy's standard model reloads (about 1.5 minutes). Reachy's local replies will not work until then. You will get a notification here and a Telegram message when Reachy is back online.`}
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setDeepTask(null)}>
            Cancel
          </Button>
          <Button onClick={() => void beginDeep()}>Start deep review</Button>
        </div>
      </Dialog>
    </Card>
  );
}

function TitleDialog({ open, meeting, onClose, onSaved }: { open: boolean; meeting: Meeting; onClose: () => void; onSaved: (m: Meeting) => void }) {
  return (
    <Dialog open={open} title="Meeting title" onClose={onClose}>
      {open && <TitleForm meeting={meeting} onClose={onClose} onSaved={onSaved} />}
    </Dialog>
  );
}

function TitleForm({ meeting, onClose, onSaved }: { meeting: Meeting; onClose: () => void; onSaved: (m: Meeting) => void }) {
  const [title, setTitleText] = useState(meeting.title);
  const [description, setDescription] = useState(meeting.description ?? '');
  const [status, setStatus] = useState('');
  const save = useMutation({ mutationFn: () => setTitle(meeting.id, title.trim(), description.trim()), onSuccess: (m) => (onSaved(m), onClose()) });
  const regenerate = useMutation({
    mutationFn: () => describeMeeting(meeting.id),
    onMutate: () => setStatus('Writing…'),
    onSuccess: (m) => (onSaved(m), onClose()),
    onError: (e) => setStatus(messageOf(e)),
  });
  const field = 'mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2';
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (title.trim()) save.mutate(undefined, { onError: (err) => setStatus(messageOf(err)) });
      }}
    >
      <h2 className="mb-3 text-lg font-semibold">Meeting title</h2>
      <label className="mb-2 block text-sm">
        Title
        <input className={field} value={title} maxLength={200} required autoComplete="off" onChange={(e) => setTitleText(e.target.value)} />
      </label>
      <label className="mb-2 block text-sm">
        Description
        <textarea className={field} rows={3} maxLength={400} placeholder="One or two lines on what the meeting covered" value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <p role="status" className="min-h-5 text-sm text-[var(--muted)]">{status}</p>
      <Button variant="secondary" disabled={!meeting.transcript_segments?.length || regenerate.isPending} onClick={() => regenerate.mutate()}>
        Write again from the transcript
      </Button>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit">Save</Button>
      </div>
    </form>
  );
}

function SpeakerDialog({ label, meeting, onClose, onSaved, onError }: { label: string | null; meeting: Meeting; onClose: () => void; onSaved: (m: Meeting) => void; onError: (t: string) => void }) {
  const [name, setName] = useState('');
  useEffect(() => setName(label ? (meeting.speaker_names[label] ?? '') : ''), [label, meeting.speaker_names]);
  const save = async (value: string) => {
    if (!label) return;
    onClose();
    try {
      onSaved(await renameSpeaker(meeting.id, label, value));
    } catch (e) {
      if (!(e instanceof StaleSessionError)) onError(messageOf(e));
    }
  };
  const named = label ? meeting.speaker_names[label] : undefined;
  return (
    <Dialog open={label !== null} title="Name this speaker" onClose={onClose}>
      <h2 className="mb-3 text-lg font-semibold">{label ? `Who is ${speakerName(meeting, label)}?` : ''}</h2>
      <label className="block text-sm">
        Name
        <input className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2" value={name} maxLength={60} autoComplete="off" onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        {named && (
          <Button variant="secondary" onClick={() => void save('')}>
            Clear name
          </Button>
        )}
        <Button onClick={() => name.trim() && void save(name.trim())}>Save</Button>
      </div>
    </Dialog>
  );
}

function LineDialog({ index, meeting, onClose, onSaved, onError }: { index: number | null; meeting: Meeting; onClose: () => void; onSaved: (m: Meeting) => void; onError: (t: string) => void }) {
  const segment = index === null ? null : meeting.transcript_segments?.[index];
  const current = index === null ? undefined : meeting.transcript_corrections[String(index)];
  const [text, setText] = useState('');
  useEffect(() => setText(current ?? segment?.text ?? ''), [current, segment]);
  const done = async (call: () => Promise<Meeting>) => {
    onClose();
    try {
      onSaved(await call());
    } catch (e) {
      if (!(e instanceof StaleSessionError)) onError(messageOf(e));
    }
  };
  return (
    <Dialog open={index !== null && Boolean(segment)} title="Edit line" onClose={onClose}>
      <h2 className="mb-1 text-lg font-semibold">{segment ? `Edit line at ${formatTimestamp(segment.start)}` : ''}</h2>
      {current !== undefined && segment && <p className="mb-2 text-sm text-[var(--muted)]">{`Original: ${segment.text}`}</p>}
      <label className="block text-sm">
        Text
        <textarea className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2" rows={4} maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        {current !== undefined && (
          <Button variant="secondary" onClick={() => index !== null && void done(() => revertLine(meeting.id, index))}>
            Restore original
          </Button>
        )}
        <Button onClick={() => text.trim() && index !== null && void done(() => correctLine(meeting.id, index, text.trim()))}>Save</Button>
      </div>
    </Dialog>
  );
}
