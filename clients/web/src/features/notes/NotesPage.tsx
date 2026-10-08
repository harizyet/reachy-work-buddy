import { useRef, useState } from 'react';
import type { Note } from '../../api/types';
import { EmptyState, ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { groupNotes, preview, shortDate } from './grouping';
import { useNotesEditor } from './useNotesEditor';

export function NotesPage() {
  const ctl = useNotesEditor();
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const [confirming, setConfirming] = useState(false);
  const { editor } = ctl;
  const editing = editor.selectedId !== null || editor.draftOpen;
  const list = ctl.notes.data ?? [];
  const selected = list.find((n) => n.id === editor.selectedId) ?? (ctl.saved?.id === editor.selectedId ? ctl.saved : undefined);

  return (
    <div className="grid min-h-[32rem] overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] md:grid-cols-[11rem_20rem_1fr]">
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] p-3 md:col-span-3">
          {editing && (
            <Button variant="secondary" className="md:hidden" onClick={() => void ctl.close()}>
            ‹ Notes
            </Button>
          )}
          <Button variant="secondary" aria-label="New note" onClick={() => void ctl.create()}>
            ✎ New note
          </Button>
          <Button variant="secondary" onClick={() => void ctl.refresh()}>
            Refresh
          </Button>
          <span role="status" className="flex-1 text-sm text-[var(--muted)]">
            {ctl.status}
          </span>
          <Button variant="secondary" aria-label="Delete note" disabled={!editor.selectedId} onClick={() => setConfirming(true)}>
            🗑 Delete
          </Button>
        </div>
      <nav aria-label="Folders" className="hidden border-r border-[var(--border)] p-3 md:block">
        <h1 className="mb-2 text-lg font-semibold">Notes</h1>
        <button type="button" aria-current="true" className="flex w-full justify-between rounded bg-[var(--hover)] px-2 py-1 text-left text-sm">
          All Notes <span className="text-[var(--muted)]">{list.length}</span>
        </button>
      </nav>

      <section aria-label="Notes list" className={`border-r border-[var(--border)] p-3 ${editing ? 'hidden md:block' : ''}`}>
        <h1 className="mb-2 text-lg font-semibold md:hidden">Notes</h1>
        <input
          type="search"
          aria-label="Search all notes"
          placeholder="Search all notes"
          autoComplete="off"
          className="mb-3 w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2 text-sm"
          value={ctl.search}
          onChange={(e) => ctl.setSearch(e.target.value)}
        />
        {ctl.notes.isPending && <p role="status" className="text-sm text-[var(--muted)]">Loading…</p>}
        {ctl.notes.error && !ctl.notes.data && <ErrorState message={ctl.notes.error.message} onRetry={() => void ctl.notes.refetch()} />}
        {ctl.notes.data && list.length === 0 && <EmptyState>No notes.</EmptyState>}
        {groupNotes(list).map(([section, items]) => (
          <div key={section}>
            <h2 className="mt-3 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">{section}</h2>
            <ul className="divide-y divide-[var(--border)]">
              {items.map((note) => (
                <li key={note.id} className={note.id === editor.selectedId ? 'bg-[var(--hover)]' : ''}>
                  <NoteRow note={note} current={note.id === editor.selectedId} onOpen={() => void ctl.open(note)} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      <section aria-label="Note" className={`flex flex-col p-3 ${editing ? '' : 'hidden md:flex'}`}>
        {editing ? (
          <>
            <p className="mb-2 text-center text-xs text-[var(--muted)]">
              {selected ? new Date(selected.updated_at).toLocaleString([], { dateStyle: 'long', timeStyle: 'short' }) : ''}
            </p>
            <input
              autoFocus={editor.draftOpen}
              aria-label="Title"
              placeholder="Title"
              maxLength={200}
              autoComplete="off"
              className="mb-2 w-full bg-transparent text-xl font-semibold outline-none"
              value={editor.title}
              onChange={(e) => ctl.edit({ title: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  bodyRef.current?.focus();
                }
              }}
            />
            <textarea
              ref={bodyRef}
              aria-label="Note"
              placeholder="Start writing"
              maxLength={20000}
              className="min-h-64 w-full flex-1 resize-none bg-transparent outline-none"
              value={editor.body}
              onChange={(e) => ctl.edit({ body: e.target.value })}
            />
          </>
        ) : (
          <p className="py-10 text-center text-sm text-[var(--muted)]">Select a note, or choose New note to start one.</p>
        )}
      </section>

      <Dialog open={confirming} title="Delete this note?" onClose={() => setConfirming(false)}>
        <h2 className="text-lg font-semibold">Delete this note?</h2>
        <p className="my-3 break-words text-sm">{`“${selected?.title ?? editor.title}” will be deleted. This cannot be undone.`}</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirming(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              setConfirming(false);
              if (selected) void ctl.remove(selected);
            }}
          >
            Delete
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

function NoteRow({ note, current, onOpen }: { note: Note; current: boolean; onOpen: () => void }) {
  return (
    <button type="button" aria-current={current} className="block w-full px-2 py-2 text-left" onClick={onOpen}>
      <strong className="block break-words">{note.title}</strong>
      <span className="block break-words text-sm">
        <span>{shortDate(note.updated_at)}</span> <span className="text-[var(--muted)]">{preview(note)}</span>
      </span>
      <span className="text-xs text-[var(--muted)]">🗀 Notes</span>
    </button>
  );
}
