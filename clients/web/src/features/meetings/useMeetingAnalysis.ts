import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { analysisEnabled, confirmAction, dismissItem, getAnalysis, retryAnalysis, startAnalysis } from '../../api/meetingAnalysis';

const CONFIG = ['meeting-analysis', 'config'] as const;
const status = (meetingId: string) => ['meeting-analysis', 'status', meetingId] as const;

export const POLL_MS = 2000;

export const useAnalysisEnabled = () => useQuery({ queryKey: CONFIG, queryFn: ({ signal }) => analysisEnabled(signal), staleTime: 60_000 });

// Reloaded while a run is waiting or working; the server, not this page, says what state a meeting is in.
export const useMeetingAnalysis = (meetingId: string, enabled: boolean) =>
  useQuery({
    queryKey: status(meetingId),
    queryFn: ({ signal }) => getAnalysis(meetingId, signal),
    enabled,
    refetchOnMount: 'always',
    refetchInterval: (query) => (query.state.data && ['queued', 'processing'].includes(query.state.data.state) ? POLL_MS : false),
  });

export function useAnalysisActions(meetingId: string) {
  const client = useQueryClient();
  const key = status(meetingId);
  return {
    start: useMutation({ mutationFn: (force: boolean) => startAnalysis(meetingId, { force }), onSuccess: (data) => client.setQueryData(key, data) }),
    retry: useMutation({ mutationFn: (runId: string) => retryAnalysis(runId), onSuccess: (data) => client.setQueryData(key, data) }),
    confirm: useMutation({
      mutationFn: (v: { id: string; text?: string }) => confirmAction(v.id, v.text === undefined ? {} : { text: v.text }),
      onSettled: () => {
        void client.invalidateQueries({ queryKey: key });
        void client.invalidateQueries({ queryKey: ['planner'] });
      },
    }),
    dismiss: useMutation({ mutationFn: (itemId: string) => dismissItem(itemId), onSettled: () => void client.invalidateQueries({ queryKey: key }) }),
  };
}
