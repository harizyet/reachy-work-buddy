import { useCallback, useEffect, useRef, useState } from 'react';
import { StaleSessionError } from '../../api/client';
import { getMotion, listRobots, putMotion } from '../../api/voice';
import type { MotionSettings } from '../../api/types';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { VOICE_STATE_LABELS, useVoice } from '../voice/VoiceProvider';
import { Check, selectClass } from './fields';

export function VoiceTab() {
  return (
    <div className="space-y-4">
      <MicrophoneCard />
      <MotionCard />
    </div>
  );
}

function MicrophoneCard() {
  const voice = useVoice();
  const { selected, session, active } = voice;
  const state = session?.state ?? 'stopped';
  const detail = [
    session?.state === 'stopped' && session.stop_reason ? `Stopped: ${session.stop_reason}` : '',
    active && session?.last_error ? `Last problem: ${session.last_error}` : '',
    active && state === 'listening' ? 'Wait for "Listening" before each turn; Reachy does not listen while it thinks or speaks.' : '',
    voice.detail,
  ]
    .filter(Boolean)
    .join(' · ');
  const wakeDetail = (() => {
    if (selected?.wake_armed) {
      const parts = [selected.wake_capable ? 'Privacy mode off: listening for “Hey Reachy”' : 'Privacy mode off, robot not listening yet'];
      if (selected.wake_counts.candidates) parts.push(`${selected.wake_counts.candidates} heard, ${selected.wake_counts.admitted} answered`);
      return parts.join(' · ');
    }
    if (selected && selected.online && !selected.wake_capable) return 'This robot cannot listen for “Hey Reachy”';
    return selected ? 'Privacy mode on: not listening for “Hey Reachy”' : '';
  })();
  return (
    <Card eyebrow="SPEAK TO REACHY" title="Robot microphone">
      <p role="status" className="mb-2 font-medium">
        {(VOICE_STATE_LABELS[state] ?? state) + (active && session?.wake_started ? ' (woken by voice)' : '')}
      </p>
      <p className="mb-3 rounded border border-[var(--warn)] bg-[var(--warn-bg)] p-2 text-sm text-[var(--warn)]">
        Reachy does not recognise who is speaking. While listening is on, anyone near the robot can talk to it, so use it only in a private room. Replies that shouldn't be said aloud appear here instead of on the speaker. “Hey Reachy” keeps the microphone listening for its name until you turn it off, even after a restart, and anyone who says it can start a conversation.
      </p>
      <form
        className="mb-3 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void voice.start();
        }}
      >
        <label className="text-sm">
          Robot
          <select
            className={selectClass}
            value={voice.robotId}
            disabled={voice.busy || active || voice.robots.length === 0}
            onChange={(e) => voice.setRobotId(e.target.value)}
          >
            {voice.robots.length === 0 && <option value="">No robot connected</option>}
            {voice.robots.map((r) => (
              <option key={r.robot_id} value={r.robot_id}>
                {r.voice_capable ? r.robot_id : `${r.robot_id} (${r.online ? 'voice not enabled' : 'offline'})`}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" disabled={voice.busy || active || !selected?.voice_capable}>
          Start listening
        </Button>
        <Button variant="secondary" disabled={voice.busy || !active} onClick={() => void voice.stop()}>
          Stop
        </Button>
      </form>
      <div className="flex flex-wrap items-center gap-2">
        {/* Turning privacy mode back on stays possible while the robot is offline. */}
        <Button variant="secondary" disabled={voice.busy || !selected || !(selected.wake_capable || selected.wake_armed)} onClick={() => void voice.toggleWake()}>
          {selected?.wake_armed ? 'Turn on privacy mode' : 'Turn off privacy mode'}
        </Button>
        <span role="status" className="text-sm text-[var(--muted)]">{wakeDetail}</span>
      </div>
      <p role="status" className="mt-2 text-sm text-[var(--muted)]">{detail}</p>
    </Card>
  );
}

// Animation switches for a robot. Every read and write carries a version so a slow answer for a robot the owner has
// moved away from is dropped, and a failed write requires a fresh read instead of showing an unsaved draft as applied.
function MotionCard() {
  const [robots, setRobots] = useState<string[]>([]);
  const [robotId, setRobotId] = useState('');
  const [settings, setSettings] = useState<MotionSettings | null>(null);
  const [gestures, setGestures] = useState(false);
  const [wobble, setWobble] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const version = useRef(0);

  const read = useCallback(async (id: string) => {
    const mine = ++version.current;
    setSettings(null);
    setGestures(false);
    setWobble(false);
    if (!id) return;
    setStatus('Loading animation settings…');
    try {
      const s = await getMotion(id);
      if (mine !== version.current) return;
      setSettings(s);
      setGestures(s.conversation_motion);
      setWobble(s.speech_wobble);
      setStatus(s.conversation_active ? 'Stop listening, then refresh to change animations.' : 'Current animation settings loaded.');
    } catch (e) {
      if (mine === version.current && !(e instanceof StaleSessionError)) setStatus(e instanceof Error ? e.message : 'Could not read the robot');
    }
  }, []);

  const loadRobots = useCallback(async () => {
    setStatus('Loading robots…');
    try {
      const list = (await listRobots()).map((r) => r.robot_id);
      setRobots(list);
      const next = list.includes(robotId) ? robotId : (list[0] ?? '');
      setRobotId(next);
      if (next) await read(next);
      else setStatus('No robots registered.');
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setStatus(e instanceof Error ? e.message : 'Could not list robots');
    }
  }, [read, robotId]);

  useEffect(() => {
    void loadRobots();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function apply() {
    if (busy || !settings || settings.conversation_active) return;
    const mine = ++version.current;
    setBusy(true);
    setStatus('Applying animation settings…');
    try {
      const next = await putMotion(robotId, { conversation_motion: gestures, speech_wobble: wobble });
      if (mine !== version.current) return;
      setSettings(next);
      setGestures(next.conversation_motion);
      setWobble(next.speech_wobble);
      setStatus('Animation settings applied for the next conversation.');
    } catch (e) {
      if (mine !== version.current || e instanceof StaleSessionError) return;
      // The robot may already have changed. Do not show the draft as applied.
      setSettings(null);
      setGestures(false);
      setWobble(false);
      setStatus(`${e instanceof Error ? e.message : 'Failed'}. Refresh to check the robot's current settings.`);
    } finally {
      if (mine === version.current) setBusy(false);
    }
  }

  const editable = settings !== null && !settings.conversation_active && !busy;
  return (
    <Card eyebrow="SETTINGS" title="Conversational animations">
      <p className="mb-3 text-sm">Choose how Reachy moves during robot microphone conversations. Stop listening before changing these settings.</p>
      <label className="mb-2 block text-sm">
        Robot
        <select
          className={selectClass}
          value={robotId}
          disabled={busy || robots.length === 0}
          onChange={(e) => {
            setRobotId(e.target.value);
            void read(e.target.value);
          }}
        >
          {robots.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
      </label>
      <Button variant="secondary" disabled={busy} onClick={() => void loadRobots()}>
        Refresh animation settings
      </Button>
      <form
        className="mt-3"
        onSubmit={(e) => {
          e.preventDefault();
          void apply();
        }}
      >
        <Check label="Listening and thinking gestures" checked={gestures} disabled={!editable} onChange={setGestures} />
        <p className="-mt-2 mb-3 text-sm text-[var(--muted)]">Recorded gestures while listening and thinking, with returns to the home pose between gestures.</p>
        <Check label="Head movement while speaking" checked={wobble} disabled={!editable} onChange={setWobble} />
        <p className="-mt-2 mb-3 text-sm text-[var(--muted)]">Small head movements that follow Reachy's speech.</p>
        <Button type="submit" disabled={!editable}>
          Apply animation settings
        </Button>
      </form>
      <p role="status" className="mt-2 text-sm">{status}</p>
      <p className="mt-2 text-sm text-[var(--muted)]">Applies to the next conversation. Restarting the robot's embodiment service restores its startup defaults.</p>
    </Card>
  );
}
