import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { StaleSessionError } from '../../api/client';
import { getVoiceOverview, renewVoice, setWakeArmed, startVoice, stopVoice } from '../../api/voice';
import type { VoiceOverview, VoiceRobot, VoiceSession } from '../../api/types';
import { useChat } from '../chat/ChatProvider';

export const RENEW_MS = 1500;
export const WAKE_POLL_MS = 3000;
export const OVERVIEW_POLL_MS = 10_000;

export const VOICE_STATE_LABELS: Record<string, string> = {
  starting: 'Starting…',
  listening: 'Listening — speak now',
  thinking: 'Thinking…',
  speaking: 'Speaking',
  stopped: 'Off',
};

const messageOf = (e: unknown) => (e instanceof Error ? e.message : 'unknown error');
const isActive = (s: VoiceSession | null) => Boolean(s && s.state !== 'stopped');

// The hub owns the conversation; this only starts and stops it and renews its short lease while the app is open.
// Leaving the Voice tab must not end it, so the renewing lives here, above the pages. Closing the app, signing out
// or losing the login lets the lease lapse, which stops capture on the robot.
function useVoiceController() {
  const chat = useChat();
  const queryClient = useQueryClient();
  const [session, setSession] = useState<VoiceSession | null>(null);
  const [robotId, setRobotId] = useState('');
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState('');
  const shown = useRef(0);
  const known = useRef<string | null>(null);
  const loaded = useRef(false);
  const append = chat.appendVoiceTurn;

  const active = isActive(session);
  const overview = useQuery({
    queryKey: ['voice', 'overview'],
    queryFn: ({ signal }) => getVoiceOverview(signal),
    retry: false,
    // While "Hey Reachy" is armed the page watches more closely, so a session the wake phrase opened appears quickly.
    refetchInterval: (query) => (query.state.data?.robots.some((r) => r.wake_armed) && !active ? WAKE_POLL_MS : OVERVIEW_POLL_MS),
  });
  const robots = overview.data?.robots ?? [];

  const render = useCallback(
    (status: VoiceSession | null) => {
      setSession(status);
      for (const turn of status?.turns ?? []) {
        if (turn.turn <= shown.current) continue;
        shown.current = turn.turn;
        append(turn);
        void queryClient.invalidateQueries({ queryKey: ['chat', 'session'] });
      }
    },
    [append, queryClient],
  );

  useEffect(() => {
    const data: VoiceOverview | undefined = overview.data;
    if (!data) return;
    if (data.session) {
      // A session that ended before this page loaded must not replay its turns; one found later (the wake phrase
      // opened it) shows them all.
      if (data.session.voice_session_id !== known.current) {
        known.current = data.session.voice_session_id;
        shown.current = loaded.current ? 0 : Math.max(0, ...data.session.turns.map((t) => t.turn));
      }
      render(data.session);
    }
    loaded.current = true;
  }, [overview.data, render]);

  // Pick a robot: keep the choice, else the first one that can hold a conversation.
  useEffect(() => {
    if (robots.some((r) => r.robot_id === robotId)) return;
    setRobotId((robots.find((r) => r.voice_capable) ?? robots[0])?.robot_id ?? '');
  }, [robots, robotId]);

  const sessionId = session?.voice_session_id;
  useEffect(() => {
    if (!active || !sessionId) return;
    const id = setInterval(() => {
      renewVoice(sessionId)
        .then(render)
        .catch((e: unknown) => {
          if (!(e instanceof StaleSessionError)) setDetail(`Could not reach the hub: ${messageOf(e)}. Listening stops automatically if this continues.`);
        });
    }, RENEW_MS);
    return () => clearInterval(id);
  }, [active, sessionId, render]);

  const selected: VoiceRobot | undefined = robots.find((r) => r.robot_id === robotId);

  const start = async () => {
    if (busy || active || !selected?.voice_capable) return;
    setBusy(true);
    setDetail('');
    try {
      const status = await startVoice(robotId, chat.user);
      known.current = status.voice_session_id;
      shown.current = Math.max(0, ...status.turns.map((t) => t.turn));
      render(status);
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setDetail(`Could not start listening: ${messageOf(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!session || !active) return;
    setBusy(true);
    try {
      render(await stopVoice(session.voice_session_id));
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setDetail(`Stop request failed: ${messageOf(e)}. Listening also stops when this page stops renewing it.`);
    } finally {
      setBusy(false);
    }
  };

  const toggleWake = async () => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      const next = await setWakeArmed(selected.robot_id, !selected.wake_armed, chat.user);
      queryClient.setQueryData(['voice', 'overview'], next);
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setDetail(`Could not change privacy mode: ${messageOf(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const problem = overview.error && !(overview.error instanceof StaleSessionError) ? `Robot microphone status unavailable: ${overview.error.message}` : '';
  return { robots, robotId, setRobotId, selected, session, active, busy, detail: detail || problem, start, stop, toggleWake };
}

export type VoiceController = ReturnType<typeof useVoiceController>;
const VoiceContext = createContext<VoiceController | null>(null);

export function VoiceProvider({ children }: { children: ReactNode }) {
  return <VoiceContext.Provider value={useVoiceController()}>{children}</VoiceContext.Provider>;
}

export function useVoice(): VoiceController {
  const value = useContext(VoiceContext);
  if (!value) throw new Error('useVoice needs a VoiceProvider');
  return value;
}
