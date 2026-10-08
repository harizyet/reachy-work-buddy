import { useQuery } from '@tanstack/react-query';
import { fetchStatus } from '../../api/status';

export const STATUS_POLL_MS = 10_000;

// Polling pauses while the tab is hidden (TanStack's default) and resumes on focus.
export function useStatus() {
  return useQuery({
    queryKey: ['status'],
    queryFn: ({ signal }) => fetchStatus(signal),
    refetchInterval: STATUS_POLL_MS,
  });
}
