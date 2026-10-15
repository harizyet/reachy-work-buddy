import { useQuery } from '@tanstack/react-query';
import { getEmailConfig, getSuggestions, listDrafts, listGroups, type DraftDto } from '../../api/meetingEmail';

export const EMAIL_CONFIG = ['meeting-email', 'config'] as const;
export const emailDrafts = (meetingId: string) => ['meeting-email', 'drafts', meetingId] as const;
export const POLL_MS = 5000;

/** Whether the owner's server has the feature on; the Share minutes button only exists when it does. */
export const useEmailConfig = () => useQuery({ queryKey: EMAIL_CONFIG, queryFn: ({ signal }) => getEmailConfig(signal), staleTime: 30_000 });

const ACTIVE = ['queued', 'sending'];
/** Reloaded while a message waits or is being sent: the server says where it is. */
export const useMeetingDrafts = (meetingId: string, enabled: boolean) =>
  useQuery({
    queryKey: emailDrafts(meetingId),
    queryFn: ({ signal }) => listDrafts(meetingId, signal),
    enabled,
    refetchOnMount: 'always',
    refetchInterval: (query) => ((query.state.data as DraftDto[] | undefined)?.some((d) => ACTIVE.includes(d.status)) ? POLL_MS : false),
  });

export const useSuggestions = (meetingId: string, enabled: boolean) => useQuery({ queryKey: ['meeting-email', 'suggestions', meetingId], queryFn: ({ signal }) => getSuggestions(meetingId, signal), enabled });
export const useGroups = (enabled = true) => useQuery({ queryKey: ['meeting-email', 'groups'], queryFn: ({ signal }) => listGroups(signal), enabled });
