import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { acceptProposal, dismissProposal, getLinks, getProcessing, processingEnabled, retryJob, sendForProcessing, setLink, type AcceptBody } from '../../api/notepadProcessing';
import { listMeetings } from '../../api/meetings';

const CONFIG = ['notepad-processing', 'config'] as const;
const status = (noteId: string) => ['notepad-processing', 'status', noteId] as const;
const links = (noteId: string) => ['notepad-processing', 'links', noteId] as const;

export const POLL_MS = 1500;

export const useProcessingEnabled = () => useQuery({ queryKey: CONFIG, queryFn: ({ signal }) => processingEnabled(signal), staleTime: 60_000 });

// Reloaded while a job is waiting or running; the server, not this page, says what state a note is in.
export const useNoteProcessing = (noteId: string | null, enabled: boolean) =>
  useQuery({
    queryKey: status(noteId ?? ''),
    queryFn: ({ signal }) => getProcessing(noteId!, signal),
    enabled: enabled && noteId !== null,
    refetchOnMount: 'always',
    refetchInterval: (query) => (query.state.data && ['queued', 'processing'].includes(query.state.data.state) ? POLL_MS : false),
  });

export const useMeetingLinks = (noteId: string | null, enabled: boolean) =>
  useQuery({ queryKey: links(noteId ?? ''), queryFn: ({ signal }) => getLinks(noteId!, signal), enabled: enabled && noteId !== null, refetchOnMount: 'always' });

export const useRecentMeetings = (enabled: boolean) => useQuery({ queryKey: ['notepad-processing', 'meetings'], queryFn: ({ signal }) => listMeetings(signal), enabled, staleTime: 30_000 });

export function useProcessingActions(noteId: string | null) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: ['notepad-processing'] });
  const key = status(noteId ?? '');
  return {
    send: useMutation({
      mutationFn: (v: { id: string; expected_hash?: string; force?: boolean; include_meetings?: boolean }) => sendForProcessing(v.id, { expected_hash: v.expected_hash, force: v.force, include_meetings: v.include_meetings }),
      onSuccess: (data) => client.setQueryData(status(data.note_id), data),
    }),
    retry: useMutation({ mutationFn: (jobId: string) => retryJob(jobId), onSuccess: (data) => client.setQueryData(status(data.note_id), data) }),
    accept: useMutation({ mutationFn: (v: { id: string; body: AcceptBody }) => acceptProposal(v.id, v.body), onSettled: () => { void client.invalidateQueries({ queryKey: key }); void client.invalidateQueries({ queryKey: ['planner'] }); } }),
    dismiss: useMutation({ mutationFn: (proposalId: string) => dismissProposal(proposalId), onSettled: () => void client.invalidateQueries({ queryKey: key }) }),
    link: useMutation({ mutationFn: (v: { meetingId: string; state: 'confirmed' | 'rejected' }) => setLink(noteId!, v.meetingId, v.state), onSuccess: (data) => client.setQueryData(links(noteId ?? ''), data), onSettled: () => void refresh() }),
  };
}
