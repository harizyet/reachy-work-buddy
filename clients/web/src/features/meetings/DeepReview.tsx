import { useQuery } from '@tanstack/react-query';
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { currentDeepJob, getDeepJob } from '../../api/meetings';
import type { DeepJob } from '../../api/types';
import { useNotice } from '../../components/shared/notice';

interface DeepApi {
  job: DeepJob | null;
  unavailable: boolean;
  follow(jobId: string): void;
  /** Look for a review already running (after a reload); called when the Meetings page opens. */
  resume(): void;
}
const DeepContext = createContext<DeepApi | null>(null);

export const DEEP_POLL_MS = 4000;
const finished = (job: DeepJob) => job.status === 'done' || job.status === 'failed';

// The larger local model takes the GPU and Reachy's own model with it, so a running review is shown on every
// page, followed until Reachy is back, and announced when it ends.
export function DeepReviewProvider({ children }: { children: ReactNode }) {
  const { setNotice } = useNotice();
  const [jobId, setJobId] = useState<string | null>(null);
  const [resuming, setResuming] = useState(false);
  const announced = useRef<string | null>(null);

  const current = useQuery({ queryKey: ['deep', 'current'], queryFn: ({ signal }) => currentDeepJob(signal), enabled: resuming, retry: false });
  useEffect(() => {
    if (current.data && !finished(current.data)) setJobId(current.data.id);
  }, [current.data]);

  const job = useQuery({
    queryKey: ['deep', 'job', jobId],
    queryFn: ({ signal }) => getDeepJob(jobId as string, signal),
    enabled: jobId !== null,
    // Keep trying through a brief connection loss: the review itself continues on the server.
    refetchInterval: (query) => (query.state.data && finished(query.state.data) ? false : DEEP_POLL_MS),
    retry: false,
  });

  useEffect(() => {
    const data = job.data;
    if (!data || !finished(data) || announced.current === data.id) return;
    announced.current = data.id;
    const title = data.meeting_title || 'your meeting';
    const what = ({ summary: 'deep summary', minutes: 'deep minutes' } as Record<string, string>)[data.task ?? ''] ?? 'deep review';
    const text = !data.reachy_online
      ? `Reachy's standard model could not be reloaded after the ${what} of "${title}". It needs manual recovery.`
      : data.status === 'failed'
        ? `The ${what} of "${title}" did not complete (${data.error || 'unknown error'}), but Reachy is back online.`
        : `The ${what} of "${title}" is complete. Reachy is back online.`;
    setNotice(text);
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      new Notification(data.reachy_online ? 'Reachy is available again' : 'Reachy needs attention', { body: text });
    }
  }, [job.data, setNotice]);

  const data = job.data ?? null;
  const unavailable = data !== null && (!finished(data) || data.reachy_unavailable);
  const value: DeepApi = { job: data, unavailable, follow: setJobId, resume: () => setResuming(true) };
  return (
    <DeepContext.Provider value={value}>
      {unavailable && (
        <div role="status" aria-live="polite" className="mx-auto max-w-5xl px-4 pt-2">
          <div className="rounded border border-[var(--warn)] bg-[var(--warn-bg)] p-2 text-sm text-[var(--warn)]">
            <strong>Reachy is unavailable: deep review in progress.</strong> <span>{data?.stage}</span>
          </div>
        </div>
      )}
      {children}
    </DeepContext.Provider>
  );
}

export function useDeepReview(): DeepApi {
  const value = useContext(DeepContext);
  if (!value) throw new Error('useDeepReview needs a DeepReviewProvider');
  return value;
}
