import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  askDocument,
  deleteDocument,
  getDocument,
  libraryEnabled,
  listDocuments,
  listSummaries,
  patchDocument,
  reprocessDocument,
  searchDocument,
  startSummary,
  uploadDocument,
  type DocumentDto,
  type DocumentPatch,
  type SummaryDto,
  type SummaryStyle,
  type Tier,
  type UploadInput,
} from '../../api/documents';

const KEY = ['documents'] as const;
export const POLL_MS = 2500;
export const WAITING: DocumentDto['state'][] = ['uploaded', 'queued', 'processing', 'partial'];
export const waiting = (d: Pick<DocumentDto, 'state'>) => WAITING.includes(d.state);

export const useLibraryEnabled = () => useQuery({ queryKey: [...KEY, 'config'], queryFn: ({ signal }) => libraryEnabled(signal), staleTime: 60_000 });

// Reloaded while any document is still being read; the server, not this page, says what state each is in.
export const useDocuments = (enabled: boolean) =>
  useQuery({
    queryKey: [...KEY, 'list'],
    queryFn: ({ signal }) => listDocuments(signal),
    enabled,
    refetchOnMount: 'always',
    refetchInterval: (query) => (query.state.data?.some(waiting) ? POLL_MS : false),
  });

export const useDocument = (id: string | undefined) => useQuery({ queryKey: [...KEY, 'one', id ?? ''], queryFn: ({ signal }) => getDocument(id!, signal), enabled: Boolean(id) });

export const hasRunning = (list: SummaryDto[] | undefined) => Boolean(list?.some((s) => s.status === 'running'));
export const useSummaries = (id: string | undefined) =>
  useQuery({
    queryKey: [...KEY, 'summaries', id ?? ''],
    queryFn: ({ signal }) => listSummaries(id!, signal),
    enabled: Boolean(id),
    refetchOnMount: 'always',
    refetchInterval: (query) => (hasRunning(query.state.data) ? POLL_MS : false),
  });

export function useDocumentActions() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: KEY });
  return {
    upload: useMutation({ mutationFn: (input: UploadInput) => uploadDocument(input), onSettled: () => void refresh() }),
    patch: useMutation({ mutationFn: (v: { id: string; patch: DocumentPatch }) => patchDocument(v.id, v.patch), onSettled: () => void refresh() }),
    reprocess: useMutation({ mutationFn: (v: { id: string; tier?: Tier }) => reprocessDocument(v.id, v.tier), onSettled: () => void refresh() }),
    remove: useMutation({ mutationFn: (id: string) => deleteDocument(id), onSettled: () => void refresh() }),
    summarize: useMutation({ mutationFn: (v: { id: string; style: SummaryStyle; force?: boolean }) => startSummary(v.id, v.style, v.force), onSettled: () => void refresh() }),
    search: useMutation({ mutationFn: (v: { id: string; query: string }) => searchDocument(v.id, v.query) }),
    ask: useMutation({ mutationFn: (v: { user: string; id: string; text: string }) => askDocument(v.user, v.id, v.text) }),
  };
}
