import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { currentGeneration, StaleSessionError } from '../../api/client';
import { createNote, deleteNote, listNotes, saveNote } from '../../api/planner';
import type { Note } from '../../api/types';

export const SAVE_DELAY_MS = 700;
export const SEARCH_DELAY_MS = 250;
const KEY = ['planner', 'notes'] as const;

interface Editor {
  selectedId: string | null; // the note open in the editor; null for none or a brand-new note
  draftOpen: boolean; // a new note is open and not saved yet
  title: string;
  body: string;
}

const CLOSED: Editor = { selectedId: null, draftOpen: false, title: '', body: '' };

// The editor state machine of the legacy Notes tab: debounced autosave, saves serialised so a
// quick second edit never makes a second POST, a blank new note is never created, and a note
// without a title takes its first line (then "New Note").
export function useNotesEditor() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [editor, setEditorState] = useState<Editor>(CLOSED);
  const [status, setStatus] = useState('');
  const [saved, setSavedState] = useState<Note | null>(null);

  // Latest values for the async save, which must read what is in the editor when it runs, not when it was queued.
  const editorRef = useRef(editor);
  const savedRef = useRef<{ title: string; body: string } | null>(null);
  const chain = useRef<Promise<void>>(Promise.resolve());
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // The session this editor belongs to. Once it changes (logout, expiry, a new sign-in) nothing typed
  // here is sent: "still signed in" is judged by the generation, not by React state, which lags the
  // unmount that triggers the last flush.
  const generation = useRef(currentGeneration());
  const sameSession = () => currentGeneration() === generation.current;
  const queryRef = useRef(query);
  queryRef.current = query;

  const setEditor = useCallback((next: Editor) => {
    editorRef.current = next;
    setEditorState(next);
  }, []);

  useEffect(() => {
    const id = setTimeout(() => setQuery(search.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(id);
  }, [search]);

  const notes = useQuery({
    queryKey: [...KEY, query],
    queryFn: ({ signal }) => listNotes(query, signal),
    refetchOnMount: 'always',
  });

  // A note that vanished from an unfiltered list (deleted elsewhere) closes the editor.
  useEffect(() => {
    if (!notes.data || query) return;
    const open = editorRef.current;
    if (open.selectedId && !notes.data.some((n) => n.id === open.selectedId)) {
      setEditor({ ...CLOSED, draftOpen: open.draftOpen });
    }
  }, [notes.data, query, setEditor]);

  const upsert = useCallback(
    (note: Note) => {
      queryClient.setQueryData<Note[]>([...KEY, queryRef.current], (old) =>
        old ? (old.some((n) => n.id === note.id) ? old.map((n) => (n.id === note.id ? note : n)) : [note, ...old]) : old,
      );
      void queryClient.invalidateQueries({ queryKey: KEY, refetchType: 'none' }); // other searches reload when next shown
    },
    [queryClient],
  );

  const flush = useCallback((): Promise<void> => {
    clearTimeout(timer.current);
    chain.current = chain.current.then(async () => {
      if (!sameSession()) return;
      const { selectedId, draftOpen, title: rawTitle, body } = editorRef.current;
      if (!selectedId && !draftOpen) return;
      const snapshot = savedRef.current;
      const typedTitle = rawTitle.trim();
      if (snapshot && typedTitle === snapshot.title && body === snapshot.body) {
        setStatus('Saved');
        return;
      }
      if (!selectedId && !typedTitle && !body.trim()) return;
      const firstLine = body.split('\n').map((l) => l.trim()).find(Boolean) ?? '';
      const title = (typedTitle || firstLine || 'New Note').slice(0, 200);
      try {
        setStatus('Saving…');
        const note = selectedId ? await saveNote(selectedId, title, body) : await createNote(title, body);
        savedRef.current = { title: note.title, body: note.body };
        setSavedState(note);
        const now = editorRef.current;
        if (!selectedId) {
          // The note now exists: later edits are updates. Keep what was typed while the request ran.
          setEditor({ ...now, selectedId: note.id, draftOpen: false, title: now.title || note.title });
        } else if (!now.title) {
          setEditor({ ...now, title: note.title });
        }
        upsert(note);
        setStatus('Saved');
      } catch (error) {
        if (!(error instanceof StaleSessionError) && sameSession()) {
          setStatus(`Not saved: ${error instanceof Error ? error.message : 'unknown error'}`);
        }
      }
    });
    return chain.current;
  }, [setEditor, upsert]);

  const queueSave = useCallback(() => {
    clearTimeout(timer.current);
    setStatus('Editing…');
    timer.current = setTimeout(() => void flush(), SAVE_DELAY_MS);
  }, [flush]);

  // Leaving the page keeps a late edit, but only for a session that is still signed in; on sign-out
  // the unsaved text is dropped rather than sent.
  useEffect(
    () => () => {
      clearTimeout(timer.current);
      if (sameSession()) void flush();
    },
    [flush],
  );

  const edit = (patch: Partial<Pick<Editor, 'title' | 'body'>>) => {
    setEditor({ ...editorRef.current, ...patch });
    queueSave();
  };

  const open = async (note: Note) => {
    await flush();
    savedRef.current = { title: note.title, body: note.body };
    setSavedState(note);
    setEditor({ selectedId: note.id, draftOpen: false, title: note.title, body: note.body });
    setStatus('');
  };

  const create = async () => {
    await flush();
    savedRef.current = null;
    setSavedState(null);
    setEditor({ selectedId: null, draftOpen: true, title: '', body: '' });
    setStatus('');
  };

  const close = async () => {
    await flush();
    setEditor(CLOSED);
  };

  const refresh = async () => {
    await flush();
    await notes.refetch();
  };

  const remove = async (note: Note) => {
    clearTimeout(timer.current);
    try {
      await deleteNote(note.id);
      queryClient.setQueriesData<Note[]>({ queryKey: KEY }, (old) => old?.filter((n) => n.id !== note.id));
      setEditor(CLOSED);
      setStatus('');
    } catch (error) {
      if (!(error instanceof StaleSessionError) && sameSession()) {
        setStatus(error instanceof Error ? error.message : 'Could not delete');
      }
    }
  };

  return { notes, search, setSearch, editor, saved, status, edit, open, create, close, refresh, remove, flush };
}
