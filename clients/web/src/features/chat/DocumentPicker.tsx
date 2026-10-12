import { useState } from 'react';
import type { DocumentDto } from '../../api/documents';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Spinner } from '../../components/ui/Spinner';
import { useDocuments, useLibraryEnabled } from '../documents/useDocuments';

const CLASS: Record<string, string> = { public: 'Public', 'work-private': 'Work private', sensitive: 'Sensitive' };
const usable = (d: DocumentDto) => d.state === 'ready' || d.state === 'partial';

/** The documents the owner can choose to answer from. Only documents Reachy has finished reading can be chosen; the others are listed so it is clear why they are not offered. */
export function DocumentPicker({ open, onClose, onChoose, currentId }: { open: boolean; onClose: () => void; onChoose: (doc: DocumentDto) => void; currentId: string | null }) {
  const enabled = useLibraryEnabled();
  const list = useDocuments(open && enabled.data === true);
  const [filter, setFilter] = useState('');
  const shown = (list.data ?? []).filter((d) => d.title.toLowerCase().includes(filter.trim().toLowerCase()));
  return (
    <Dialog open={open} title="Choose a document" onClose={onClose}>
      <h2 className="text-lg font-semibold">Choose a document</h2>
      <p className="mt-1 text-sm text-[var(--muted)]">Reachy will answer this conversation from the document you pick, and from nothing else, until you remove or replace it.</p>
      {(list.data?.length ?? 0) > 6 && (
        <label className="mt-2 block text-sm">
          Find a document
          <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2" />
        </label>
      )}
      {(enabled.isPending || (list.isPending && enabled.data === true)) && <Spinner label="Loading documents" />}
      {enabled.data === false && <p className="mt-3 text-sm">The document library is not turned on.</p>}
      {list.error && <p role="alert" className="mt-3 text-sm text-[var(--bad)]">{list.error.message}</p>}
      {list.data && list.data.length === 0 && <p className="mt-3 text-sm text-[var(--muted)]">No documents yet. Upload one on the Documents page first.</p>}
      <ul className="mt-3 max-h-72 divide-y divide-[var(--border)] overflow-y-auto" aria-label="Documents to choose from">
        {shown.map((d) => (
          <li key={d.id} className="flex items-center gap-2 py-2">
            <span className="min-w-0 flex-1 text-sm">
              <span className="block break-words font-medium">{d.title}</span>
              <small className="text-[var(--muted)]">
                {CLASS[d.sensitivity]}
                {d.project_scope ? ` · ${d.project_scope}` : ''}
                {usable(d) ? '' : ` · ${d.state === 'failed' ? 'could not be read' : 'still being read'}`}
              </small>
            </span>
            <Button variant="secondary" disabled={!usable(d) || d.id === currentId} aria-label={`${d.id === currentId ? 'Already attached' : 'Use'}: ${d.title}`} onClick={() => onChoose(d)}>
              {d.id === currentId ? 'Attached' : 'Use'}
            </Button>
          </li>
        ))}
        {list.data && list.data.length > 0 && shown.length === 0 && <li className="py-2 text-sm text-[var(--muted)]">No matching documents.</li>}
      </ul>
      <div className="mt-3 flex justify-end">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
      </div>
    </Dialog>
  );
}
