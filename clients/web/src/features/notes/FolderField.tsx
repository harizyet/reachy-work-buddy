import { useId, useState } from 'react';
import { flatten, normaliseTag, ROOT, TagError, type FolderNode } from './folders';

/** The note's folder under All Notes. It is applied when the field loses focus or Enter is pressed, so typing "Projects/Fin" never files the note in a half-typed folder. */
export function FolderField({ tag, folders, onCommit }: { tag: string | null; folders: FolderNode[]; onCommit: (tag: string | null) => void }) {
  const listId = useId();
  const [draft, setDraft] = useState(tag ?? '');
  const [error, setError] = useState('');

  const commit = () => {
    try {
      const next = normaliseTag(draft);
      setError('');
      setDraft(next ?? '');
      if (next !== tag) onCommit(next);
    } catch (e) {
      if (!(e instanceof TagError)) throw e;
      setError(e.message);
    }
  };

  return (
    <div className="mb-2 text-sm">
      <label className="flex items-center gap-1 text-[var(--muted)]">
        <span className="shrink-0">🗀 {ROOT} /</span>
        <input
          aria-label="Folder"
          list={listId}
          placeholder="Folder, e.g. Projects/Project StarWars/Finance"
          maxLength={400}
          autoComplete="off"
          aria-invalid={error ? true : undefined}
          className="min-w-0 flex-1 bg-transparent text-[var(--fg)] outline-none"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              commit();
            }
          }}
        />
      </label>
      <datalist id={listId}>
        {flatten(folders).map((f) => (
          <option key={f.path} value={f.path} />
        ))}
      </datalist>
      {error && (
        <p role="alert" className="text-xs text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}
