import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  askAcross,
  attachDocument,
  confirmFinding,
  detachDocument,
  dismissFinding,
  getOverview,
  multimodalEnabled,
  retryRun,
  reviewWindow,
  startAlignment,
  startCombinedAnalysis,
  withdrawReview,
  type Decision,
} from '../../api/meetingMultimodal';

const CONFIG = ['meeting-multimodal', 'config'] as const;
const overview = (meetingId: string) => ['meeting-multimodal', 'overview', meetingId] as const;
export const POLL_MS = 2500;

export const useMultimodalEnabled = () => useQuery({ queryKey: CONFIG, queryFn: ({ signal }) => multimodalEnabled(signal), staleTime: 60_000 });

// Reloaded while a run is waiting or working, or an attached document is still being read; the server, not this page, says what state anything is in.
export const useOverview = (meetingId: string, enabled: boolean) =>
  useQuery({
    queryKey: overview(meetingId),
    queryFn: ({ signal }) => getOverview(meetingId, signal),
    enabled,
    refetchOnMount: 'always',
    refetchInterval: (query) => {
      const d = query.state.data;
      return d && (['queued', 'processing'].includes(d.alignment.state) || ['queued', 'processing'].includes(d.analysis.state) || d.documents.some((x) => !x.ready && x.state !== 'failed')) ? POLL_MS : false;
    },
  });

export function useMultimodalActions(meetingId: string) {
  const client = useQueryClient();
  const key = overview(meetingId);
  const refresh = () => void client.invalidateQueries({ queryKey: key });
  return {
    attach: useMutation({ mutationFn: (documentId: string) => attachDocument(meetingId, documentId), onSettled: refresh }),
    detach: useMutation({ mutationFn: (documentId: string) => detachDocument(meetingId, documentId), onSettled: refresh }),
    align: useMutation({ mutationFn: (force: boolean) => startAlignment(meetingId, force), onSuccess: (data) => client.setQueryData(key, data) }),
    analyse: useMutation({ mutationFn: (force: boolean) => startCombinedAnalysis(meetingId, force), onSuccess: (data) => client.setQueryData(key, data) }),
    retry: useMutation({ mutationFn: (runId: string) => retryRun(runId), onSuccess: (data) => client.setQueryData(key, data) }),
    review: useMutation({
      mutationFn: (v: { windowKey: string; decision: Decision; document_id?: string; page?: number }) => reviewWindow(meetingId, v.windowKey, { decision: v.decision, document_id: v.document_id, page: v.page }),
      onSettled: refresh,
    }),
    withdraw: useMutation({ mutationFn: (windowKey: string) => withdrawReview(meetingId, windowKey), onSettled: refresh }),
    ask: useMutation({ mutationFn: (question: string) => askAcross(meetingId, question) }),
    confirm: useMutation({
      mutationFn: (v: { id: string; text?: string }) => confirmFinding(v.id, v.text === undefined ? {} : { text: v.text }),
      onSettled: () => {
        refresh();
        void client.invalidateQueries({ queryKey: ['planner'] });
      },
    }),
    dismiss: useMutation({ mutationFn: (itemId: string) => dismissFinding(itemId), onSettled: refresh }),
  };
}
