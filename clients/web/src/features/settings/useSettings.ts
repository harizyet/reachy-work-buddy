import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getLlm, getPersona, getSearchLog, getWebSearch, putLlm, putPersona, putWebSearch, setSessionDnd, setSessionMode } from '../../api/settings';
import { getSession } from '../../api/chat';
import type { LlmConfig, Persona, WebSearchConfig } from '../../api/types';

// Settings are read each time their tab opens and replaced by what the hub returns after a save.
export const useLlm = () => useQuery({ queryKey: ['settings', 'llm'], queryFn: ({ signal }) => getLlm(signal), refetchOnMount: 'always' });
export const usePersona = () => useQuery({ queryKey: ['settings', 'persona'], queryFn: ({ signal }) => getPersona(signal), refetchOnMount: 'always' });
export const useWebSearch = () => useQuery({ queryKey: ['settings', 'websearch'], queryFn: ({ signal }) => getWebSearch(signal), refetchOnMount: 'always' });
export const useSearchLog = (enabled: boolean) =>
  useQuery({ queryKey: ['settings', 'websearch-log'], queryFn: ({ signal }) => getSearchLog(signal), enabled, refetchOnMount: 'always' });

export function useSaveLlm() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: putLlm,
    onSuccess: (config: LlmConfig) => {
      client.setQueryData(['settings', 'llm'], config);
      void client.invalidateQueries({ queryKey: ['status'] });
    },
  });
}
export function useSavePersona() {
  const client = useQueryClient();
  return useMutation({ mutationFn: putPersona, onSuccess: (p: Persona) => client.setQueryData(['settings', 'persona'], p) });
}
export function useSaveWebSearch() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: putWebSearch,
    // The save response omits usage; reload so the meters match what was saved.
    onSuccess: (c: WebSearchConfig) => {
      client.setQueryData(['settings', 'websearch'], c);
      void client.invalidateQueries({ queryKey: ['settings'] });
    },
  });
}

export const useSessionFor = (user: string | null) =>
  useQuery({ queryKey: ['settings', 'session', user], queryFn: ({ signal }) => getSession(user as string, signal), enabled: user !== null, retry: false, refetchOnMount: 'always' });

export function useSaveSession(user: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (v: { mode: string; dnd: boolean }) => {
      await setSessionMode(user as string, v.mode);
      await setSessionDnd(user as string, v.dnd);
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['settings', 'session'] });
      void client.invalidateQueries({ queryKey: ['chat', 'session'] });
    },
  });
}
