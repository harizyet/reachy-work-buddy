import { useSyncExternalStore } from 'react';

// Writing a summary or minutes can take a couple of minutes. The request outlives the screen that started it, so which ones are running is kept here, not in a component's state: leaving the meeting and
// coming back must still show "writing", not the old text with a button that starts a second run.
type Kind = 'summary' | 'minutes';
const running = new Map<string, string>(); // meeting:kind -> the model tier it is being written on
const listeners = new Set<() => void>();
let version = 0;
const key = (meetingId: string, kind: Kind) => `${meetingId}:${kind}`;
const emit = () => {
  version += 1;
  listeners.forEach((l) => l());
};

export function beginGeneration(meetingId: string, kind: Kind, model: string): boolean {
  if (running.has(key(meetingId, kind))) return false;
  running.set(key(meetingId, kind), model);
  emit();
  return true;
}
export function endGeneration(meetingId: string, kind: Kind): void {
  if (running.delete(key(meetingId, kind))) emit();
}

/** Which of this meeting's outputs are being written right now, from any screen that has started one. */
export function useGenerating(meetingId: string): { kind: Kind; model: string } | null {
  useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => version,
  );
  for (const kind of ['summary', 'minutes'] as const) {
    const model = running.get(key(meetingId, kind));
    if (model !== undefined) return { kind, model };
  }
  return null;
}
