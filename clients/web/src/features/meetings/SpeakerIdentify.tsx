import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { StaleSessionError } from '../../api/client';
import { confirmSpeakers, getIdentifyScreen, meetingAudioUrl, type SpeakerDecision } from '../../api/meetings';
import type { IdentifyScreen, Meeting, SpeakerCard, SpeakerSample } from '../../api/types';
import { ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Spinner } from '../../components/ui/Spinner';
import { formatTimestamp } from './format';

// Identify Speakers (Phase 54). The owner listens to a few short stretches of the recording per detected speaker and names them.
// Samples are time ranges of the meeting recording, played through the same authenticated route as the main player; nothing is
// generated or stored, and a name here is the owner's statement, not something Reachy worked out from a voice.

type Mode = 'untouched' | 'name' | 'unknown' | 'skipped';
interface Choice {
  mode: Mode;
  name: string;
}

const messageOf = (error: unknown) => (error instanceof Error ? error.message : 'Something went wrong');

export function SpeakerIdentify({ meeting, onSaved, onShow }: { meeting: Meeting; onSaved: (m: Meeting) => void; onShow: (seconds: number) => void }) {
  const screen = useQuery({ queryKey: ['meeting-identify', meeting.id], queryFn: ({ signal }) => getIdentifyScreen(meeting.id, signal), gcTime: 0, staleTime: 0 });
  if (screen.isPending) return <Spinner label="Loading speakers" />;
  if (!screen.data) return <ErrorState message={screen.error?.message ?? 'Could not load the speakers'} onRetry={() => void screen.refetch()} />;
  return <Body key={screen.data.fingerprint ?? 'none'} meeting={meeting} data={screen.data} onSaved={onSaved} onShow={onShow} reload={() => void screen.refetch()} />;
}

function initialChoice(card: SpeakerCard): Choice {
  const identity = card.identity;
  if (!identity) return { mode: 'untouched', name: '' };
  if (identity.status === 'named') return { mode: 'name', name: identity.name ?? '' };
  return { mode: identity.status, name: '' };
}

function Body({ meeting, data, onSaved, onShow, reload }: { meeting: Meeting; data: IdentifyScreen; onSaved: (m: Meeting) => void; onShow: (seconds: number) => void; reload: () => void }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [choices, setChoices] = useState<Record<string, Choice>>(() => Object.fromEntries(data.speakers.map((s) => [s.label, initialChoice(s)])));
  // Which samples are shown per speaker, and the unused ones kept for "Another sample".
  const [pools, setPools] = useState<Record<string, { shown: SpeakerSample[]; spare: SpeakerSample[] }>>(() =>
    Object.fromEntries(data.speakers.map((s) => [s.label, { shown: s.samples, spare: s.alternates }])),
  );
  const [status, setStatus] = useState('');
  const [saving, setSaving] = useState(false);

  const stopAt = useRef<number | null>(null);
  useEffect(() => () => audio.current?.pause(), []);

  const keyOf = (label: string, sample: SpeakerSample) => `${label}@${sample.start}`;
  const toggle = (label: string, sample: SpeakerSample) => {
    const player = audio.current;
    if (!player) return;
    const key = keyOf(label, sample);
    if (playing === key) {
      player.pause();
      setPlaying(null);
      return;
    }
    stopAt.current = sample.end;
    player.currentTime = Math.max(0, sample.start);
    setPlaying(key);
    void player.play?.()?.catch?.(() => setPlaying(null)); // a browser may refuse without a gesture; the click is one
  };

  const another = (label: string, sample: SpeakerSample) => {
    setPools((all) => {
      const pool = all[label]!;
      const [next, ...rest] = pool.spare;
      if (!next) return all;
      audio.current?.pause();
      setPlaying(null);
      return { ...all, [label]: { shown: pool.shown.map((s) => (s === sample ? next : s)), spare: [...rest, sample] } };
    });
  };

  const decisions = useMemo(() => {
    const out: Record<string, SpeakerDecision> = {};
    for (const card of data.speakers) {
      const choice = choices[card.label]!;
      const before = initialChoice(card);
      if (choice.mode === before.mode && choice.name.trim() === before.name.trim()) continue;
      if (choice.mode === 'name') {
        if (choice.name.trim()) out[card.label] = { status: 'named', name: choice.name.trim() };
        else if (card.identity) out[card.label] = { status: 'clear' };
      } else if (choice.mode === 'untouched') {
        if (card.identity) out[card.label] = { status: 'clear' };
      } else out[card.label] = { status: choice.mode };
    }
    return out;
  }, [choices, data.speakers]);

  const set = (label: string, next: Partial<Choice>) => setChoices((all) => ({ ...all, [label]: { ...all[label]!, ...next } }));
  const changed = Object.keys(decisions).length;

  const save = async () => {
    setSaving(true);
    setStatus('');
    try {
      onSaved(await confirmSpeakers(meeting.id, data.fingerprint, decisions));
      setStatus('Saved. The transcript now shows these names.');
      reload();
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setStatus(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const listId = `speaker-names-${meeting.id}`;
  return (
    <div>
      <audio
        ref={audio}
        preload="none"
        src={meetingAudioUrl(meeting.id)}
        onTimeUpdate={(e) => {
          if (stopAt.current !== null && e.currentTarget.currentTime >= stopAt.current) {
            e.currentTarget.pause();
            setPlaying(null);
          }
        }}
        onEnded={() => setPlaying(null)}
      />
      <p className="text-sm text-[var(--muted)]">
        Listen to a few stretches of the recording from each speaker, then say who they are. Names you save appear in the transcript, summaries and analysis. You can skip anyone you are unsure of. Reachy does not
        recognise voices: it only picked clear stretches where one detected speaker was talking.
      </p>
      {data.needs_review && (
        <p role="status" className="my-2 rounded border border-[var(--warn)] bg-[var(--warn-bg)] p-2 text-sm text-[var(--warn)]">
          {`Speaker detection was run again and the speakers changed, so the names you gave before were not applied${
            data.superseded ? ` (they were: ${Object.entries(data.superseded).map(([label, i]) => `${label}${i.name ? ` = ${i.name}` : ` ${i.status}`}`).join(', ')})` : ''
          }. Please check each speaker below.`}
        </p>
      )}
      {meeting.stale_outputs.length > 0 && (
        <p role="status" className="my-2 text-sm text-[var(--warn)]">{`The ${meeting.stale_outputs.join(' and ')} was written under different speaker names. Rerun it after you save.`}</p>
      )}
      <datalist id={listId}>
        {data.suggestions.map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>
      <ul className="mt-3 space-y-4">
        {data.speakers.map((card) => {
          const choice = choices[card.label]!;
          const pool = pools[card.label]!;
          return (
            <li key={card.label} aria-label={card.display_name} className="rounded border border-[var(--border)] p-3">
              <h4 className="font-medium">
                {card.display_name}
                <span className="ml-2 text-xs font-normal text-[var(--muted)]">{`${card.label} · ${Math.round(card.seconds)} s of speech · ${card.lines} line${card.lines === 1 ? '' : 's'}`}</span>
              </h4>
              {card.reason && <p className="text-sm text-[var(--warn)]">{card.reason}</p>}
              {pool.shown.length === 0 && !card.reason && <p className="text-sm text-[var(--muted)]">No sample is available for this speaker.</p>}
              <ul className="my-2 space-y-2">
                {pool.shown.map((sample) => {
                  const key = keyOf(card.label, sample);
                  const label = `${formatTimestamp(sample.start)}–${formatTimestamp(sample.end)}`;
                  return (
                    <li key={key} className="flex flex-wrap items-center gap-2 text-sm">
                      <Button aria-label={`${playing === key ? 'Pause' : 'Play'} ${card.display_name} sample at ${label}`} aria-pressed={playing === key} onClick={() => toggle(card.label, sample)}>
                        {playing === key ? 'Pause' : 'Play'}
                      </Button>
                      <span className="tabular-nums">{label}</span>
                      <span className="min-w-0 flex-1 break-words text-[var(--muted)]">{sample.text ? `“${sample.text}”` : ''}</span>
                      {sample.quality === 'low' && <span className="text-[var(--warn)]">{`Unclear: ${sample.notes.join('; ') || 'low quality'}`}</span>}
                      <Button variant="secondary" aria-label={`Show ${label} in the recording`} onClick={() => onShow(sample.start)}>
                        In recording
                      </Button>
                      {pool.spare.length > 0 && (
                        <Button variant="secondary" aria-label={`Another sample instead of ${label}`} onClick={() => another(card.label, sample)}>
                          Another sample
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ul>
              <div className="flex flex-wrap items-end gap-2">
                <label className="block min-w-[10rem] flex-1 text-sm">
                  {`Who is ${card.display_name}?`}
                  <input
                    className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2"
                    list={listId}
                    value={choice.mode === 'name' ? choice.name : ''}
                    maxLength={60}
                    autoComplete="off"
                    placeholder="Name"
                    onChange={(e) => set(card.label, e.target.value ? { mode: 'name', name: e.target.value } : { mode: 'untouched', name: '' })}
                  />
                </label>
                <Button variant="secondary" aria-pressed={choice.mode === 'unknown'} className={choice.mode === 'unknown' ? 'ring-2 ring-[var(--accent)]' : ''} onClick={() => set(card.label, { mode: 'unknown', name: '' })}>
                  Unknown
                </Button>
                <Button variant="secondary" aria-pressed={choice.mode === 'skipped'} className={choice.mode === 'skipped' ? 'ring-2 ring-[var(--accent)]' : ''} onClick={() => set(card.label, { mode: 'skipped', name: '' })}>
                  Skip
                </Button>
                {card.identity && (
                  <Button variant="secondary" onClick={() => set(card.label, { mode: 'untouched', name: '' })}>
                    {card.identity.status === 'named' ? 'Remove name' : 'Undo'}
                  </Button>
                )}
              </div>
              {card.identity && <p className="mt-1 text-xs text-[var(--muted)]">{card.identity.status === 'named' ? `Saved as ${card.identity.name}.` : `Saved as ${card.identity.status}.`}</p>}
            </li>
          );
        })}
      </ul>
      <div className="mt-3 flex items-center gap-3">
        <Button disabled={saving || changed === 0} onClick={() => void save()}>
          {changed === 0 ? 'Save' : `Save ${changed} change${changed === 1 ? '' : 's'}`}
        </Button>
        <p role="status" className="text-sm">{status}</p>
      </div>
    </div>
  );
}
