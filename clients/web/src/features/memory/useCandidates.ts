import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { acceptCandidate, forgetConversationCandidates, listCandidates, rejectCandidate, type AcceptBody } from '../../api/memoryCandidates';

const KEY = ['memory', 'candidates'] as const;

// The queue is reloaded each time the page opens and after every change: the hub, not this page, says what is pending.
export const useCandidates = () => useQuery({ queryKey: KEY, queryFn: ({ signal }) => listCandidates(signal), refetchOnMount: 'always' });

function useChange<V, R = unknown>(run: (value: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: run, onSettled: () => client.invalidateQueries({ queryKey: KEY }) });
}

export const useAccept = () => useChange((v: { id: string; body: AcceptBody }) => acceptCandidate(v.id, v.body));
export const useReject = () => useChange((v: { id: string; suppress: boolean }) => rejectCandidate(v.id, v.suppress));
export const useForgetConversation = () => useChange((conversationId: string) => forgetConversationCandidates(conversationId));
