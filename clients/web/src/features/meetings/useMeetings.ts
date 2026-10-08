import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { cancelMeeting, deleteMeeting, getMeeting, listMeetings, uploadMeeting } from '../../api/meetings';
import type { Meeting } from '../../api/types';

export const useMeetingList = () =>
  useQuery({ queryKey: ['meetings', 'list'], queryFn: ({ signal }) => listMeetings(signal), refetchOnMount: 'always' });

export const useMeeting = (id: string) =>
  useQuery({ queryKey: ['meetings', 'detail', id], queryFn: ({ signal }) => getMeeting(id, signal), refetchOnMount: 'always' });

/** Put a changed meeting (returned by the hub) into the open detail and refresh the list around it. */
export function useAcceptMeeting() {
  const client = useQueryClient();
  return (meeting: Meeting) => {
    client.setQueryData(['meetings', 'detail', meeting.id], meeting);
    void client.invalidateQueries({ queryKey: ['meetings', 'list'] });
  };
}

export function useUpload() {
  const client = useQueryClient();
  return useMutation({ mutationFn: uploadMeeting, onSuccess: () => client.invalidateQueries({ queryKey: ['meetings', 'list'] }) });
}

export function useDeleteMeetings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (ids: string[]) => {
      for (const id of ids) await deleteMeeting(id);
    },
    onSettled: () => client.invalidateQueries({ queryKey: ['meetings'] }),
  });
}

export function useCancelMeeting() {
  const client = useQueryClient();
  return useMutation({ mutationFn: cancelMeeting, onSettled: () => client.invalidateQueries({ queryKey: ['meetings'] }) });
}
