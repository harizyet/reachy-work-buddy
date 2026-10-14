import { useState, type FormEvent } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { StaleSessionError } from '../../api/client';
import { ACCEPTED_FILES, type DocumentDto, type Priority, type Sensitivity } from '../../api/documents';
import { EmptyState, ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Spinner } from '../../components/ui/Spinner';
import { StatusPill, type Tone } from '../../components/ui/StatusPill';
import { DocumentTools } from './DocumentTools';
import { InspectView } from './InspectView';
import { useDocumentActions, useDocuments, useLibraryEnabled } from './useDocuments';

const STATE_LABEL: Record<DocumentDto['state'], string> = {
  uploaded: 'Uploaded', queued: 'Queued', processing: 'Reading', ready: 'Ready', partial: 'Partly ready', failed: 'Failed', deleting: 'Deleting',
};
const STATE_TONE: Record<DocumentDto['state'], Tone> = { uploaded: 'warn', queued: 'warn', processing: 'warn', ready: 'good', partial: 'warn', failed: 'bad', deleting: 'warn' };
const CLASS_LABEL: Record<Sensitivity, string> = { public: 'Public', 'work-private': 'Work private', sensitive: 'Sensitive' };
const TIER_LABEL: Record<string, string> = { flash: 'Flash', basic: 'Basic', standard: 'Standard', advanced: 'Advanced' };
const WHEN = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

export const sizeLabel = (bytes: number) => (bytes >= 1_048_576 ? `${(bytes / 1_048_576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

export function DocumentsPage() {
  const { id } = useParams();
  const enabled = useLibraryEnabled();
  const list = useDocuments(enabled.data === true);
  const selected = list.data?.find((d) => d.id === id);

  return (
    <section aria-labelledby="documents-title">
      <h1 id="documents-title" className="text-xl font-semibold">Documents</h1>
      <p className="mt-1 text-sm text-[var(--muted)]">
        Upload a PDF, a presentation (PowerPoint, OpenDocument), a Word, Excel or other office file, an EPUB, an HTML page, a CSV or an image. Reachy keeps the original, reads it locally, and can answer questions about it, search it and summarise it. What it reads is a machine&apos;s reading and can contain mistakes; the original is what counts.
      </p>
      {enabled.isPending && <Spinner label="Checking the document library" />}
      {enabled.error && <ErrorState message={enabled.error.message} onRetry={() => void enabled.refetch()} />}
      {enabled.data === false && <EmptyState>The document library is not turned on.</EmptyState>}
      {enabled.data === true && (
        <>
          <UploadForm />
          <div className="mt-6">
            {list.isPending && <Spinner label="Loading documents" />}
            {list.error && !list.data && <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />}
            {list.data && list.data.length === 0 && <EmptyState>No documents yet.</EmptyState>}
            <ul className="space-y-2" aria-label="Documents">
              {(list.data ?? []).map((d) => (
                <DocumentRow key={d.id} doc={d} open={d.id === id} />
              ))}
            </ul>
          </div>
          {id && list.data && !selected && <EmptyState>That document no longer exists.</EmptyState>}
          {selected && <DocumentDetail doc={selected} />}
        </>
      )}
    </section>
  );
}

function DocumentRow({ doc, open }: { doc: DocumentDto; open: boolean }) {
  const navigate = useNavigate();
  return (
    <li>
      <button
        type="button"
        onClick={() => navigate(open ? '/documents' : `/documents/${doc.id}`)}
        aria-expanded={open}
        className={`flex w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-[var(--border)] p-3 text-left hover:bg-[var(--hover)] ${open ? 'bg-[var(--hover)]' : 'bg-[var(--surface)]'}`}
      >
        <span className="min-w-0 flex-1 font-medium [overflow-wrap:anywhere]">{doc.title}</span>
        <StatusPill tone={STATE_TONE[doc.state]}>{STATE_LABEL[doc.state]}</StatusPill>
        <span className="text-xs text-[var(--muted)]">{CLASS_LABEL[doc.sensitivity]}{doc.project_scope ? ` · ${doc.project_scope}` : ''}</span>
      </button>
    </li>
  );
}

function UploadForm() {
  const { upload } = useDocumentActions();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [project, setProject] = useState('');
  const [sensitivity, setSensitivity] = useState<Sensitivity>('work-private');
  const [priority, setPriority] = useState<Priority>('background');
  const [input, setInput] = useState(0); // re-keys the file input so it clears after an upload
  const navigate = useNavigate();

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    upload.mutate(
      { file, title, sensitivity, project_scope: project, processing_priority: priority },
      { onSuccess: (doc) => { setFile(null); setTitle(''); setInput((n) => n + 1); navigate(`/documents/${doc.id}`); } },
    );
  }
  const failure = upload.error && !(upload.error instanceof StaleSessionError) ? upload.error.message : '';
  return (
    <form onSubmit={submit} className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4" aria-label="Upload a document">
      <h2 className="font-medium">Upload</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="text-sm sm:col-span-2">
          File
          <input key={input} type="file" accept={ACCEPTED_FILES} onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="mt-1 block w-full text-sm" />
        </label>
        <label className="text-sm">
          Title (optional)
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} className="mt-1 block w-full rounded-md border border-[var(--border)] bg-[var(--surface)] p-1.5" />
        </label>
        <label className="text-sm">
          Project (optional)
          <input value={project} onChange={(e) => setProject(e.target.value)} maxLength={100} className="mt-1 block w-full rounded-md border border-[var(--border)] bg-[var(--surface)] p-1.5" />
        </label>
        <label className="text-sm">
          Class
          <select value={sensitivity} onChange={(e) => setSensitivity(e.target.value as Sensitivity)} className="mt-1 block w-full rounded-md border border-[var(--border)] bg-[var(--surface)] p-1.5">
            <option value="public">Public</option>
            <option value="work-private">Work private</option>
            <option value="sensitive">Sensitive</option>
          </select>
        </label>
        <label className="text-sm">
          Reading priority
          <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)} className="mt-1 block w-full rounded-md border border-[var(--border)] bg-[var(--surface)] p-1.5">
            <option value="background">Background</option>
            <option value="normal">Normal</option>
            <option value="interactive">Priority (better reading, slower)</option>
          </select>
        </label>
      </div>
      <p className="mt-2 text-xs text-[var(--muted)]">The class is yours to set; what a document says never changes it. Files up to 50 MB.</p>
      <Button type="submit" className="mt-3" disabled={!file || upload.isPending}>{upload.isPending ? 'Uploading…' : 'Upload'}</Button>
      {failure && <p role="alert" className="mt-2 text-sm text-[var(--bad)]">{failure}</p>}
    </form>
  );
}

function DocumentDetail({ doc }: { doc: DocumentDto }) {
  const { patch, reprocess, remove } = useDocumentActions();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const wanted = Number(params.get('page')); // a link from a meeting opens the inspector on that page
  const initialPage = Number.isInteger(wanted) && wanted >= 1 ? wanted : undefined;
  const [confirm, setConfirm] = useState(false);
  const [inspecting, setInspecting] = useState(initialPage !== undefined);
  const [title, setTitle] = useState(doc.title);
  const ready = doc.state === 'ready' || doc.state === 'partial';
  const failure = [patch, reprocess, remove].map((m) => m.error).find((e) => e && !(e instanceof StaleSessionError));

  return (
    <article className="mt-6 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4" aria-label={`Document ${doc.title}`}>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="min-w-0 flex-1 text-lg font-semibold [overflow-wrap:anywhere]">{doc.title}</h2>
        <StatusPill tone={STATE_TONE[doc.state]}>{STATE_LABEL[doc.state]}</StatusPill>
      </div>
      <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        <div><dt className="inline text-[var(--muted)]">File: </dt><dd className="inline [overflow-wrap:anywhere]">{doc.filename} ({sizeLabel(doc.size_bytes)})</dd></div>
        <div><dt className="inline text-[var(--muted)]">Uploaded: </dt><dd className="inline">{WHEN.format(new Date(doc.created_at))}</dd></div>
        <div><dt className="inline text-[var(--muted)]">Class: </dt><dd className="inline">{CLASS_LABEL[doc.sensitivity]}</dd></div>
        <div><dt className="inline text-[var(--muted)]">Project: </dt><dd className="inline">{doc.project_scope ?? 'None'}</dd></div>
        <div><dt className="inline text-[var(--muted)]">Read at: </dt><dd className="inline">{doc.tier ? TIER_LABEL[doc.tier] : 'Not yet'}{doc.page_count ? ` · ${doc.page_count} page${doc.page_count === 1 ? '' : 's'}` : ''}</dd></div>
        <div><dt className="inline text-[var(--muted)]">Original: </dt><dd className="inline font-mono text-xs">{doc.source_hash.slice(0, 12)}</dd></div>
      </dl>
      {doc.state === 'failed' && <p role="alert" className="mt-2 text-sm text-[var(--bad)]">Reachy could not read this document{doc.error_code ? ` (${doc.error_code})` : ''}. You can try reading it again.</p>}
      {doc.state === 'partial' && <p className="mt-2 text-sm text-[var(--muted)]">Only part of this document is readable so far, or it is longer than Reachy reads. Answers may not cover all of it.</p>}

      <div className="mt-4 flex flex-wrap items-end gap-2">
        <label className="text-sm">
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} className="ml-2 rounded-md border border-[var(--border)] bg-[var(--surface)] p-1.5" />
        </label>
        <Button variant="secondary" disabled={patch.isPending || !title.trim() || title === doc.title} onClick={() => patch.mutate({ id: doc.id, patch: { title: title.trim() } })}>Rename</Button>
        <label className="text-sm">
          Class
          <select value={doc.sensitivity} onChange={(e) => patch.mutate({ id: doc.id, patch: { sensitivity: e.target.value as Sensitivity } })} className="ml-2 rounded-md border border-[var(--border)] bg-[var(--surface)] p-1.5">
            <option value="public">Public</option>
            <option value="work-private">Work private</option>
            <option value="sensitive">Sensitive</option>
          </select>
        </label>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="secondary" disabled={reprocess.isPending || doc.state === 'processing'} onClick={() => reprocess.mutate({ id: doc.id })}>Read again</Button>
        {doc.next_tier && (
          <Button variant="secondary" disabled={reprocess.isPending || doc.state === 'processing'} onClick={() => reprocess.mutate({ id: doc.id, tier: doc.next_tier! })}>
            Improve reading ({TIER_LABEL[doc.next_tier]}{doc.next_tier === 'advanced' ? ', very slow' : ''})
          </Button>
        )}
        {ready && <Button variant="secondary" aria-pressed={inspecting} onClick={() => setInspecting((v) => !v)}>{inspecting ? 'Hide inspector' : 'Inspect extraction'}</Button>}
        {!confirm && <Button variant="secondary" onClick={() => setConfirm(true)}>Delete…</Button>}
      </div>
      {confirm && (
        <div role="alertdialog" aria-label="Confirm delete" className="mt-3 rounded-md border border-[var(--bad)] p-3 text-sm">
          <p>Delete &ldquo;{doc.title}&rdquo;? The original, what Reachy read from it and its summaries are all removed. This cannot be undone.</p>
          <div className="mt-2 flex gap-2">
            <Button disabled={remove.isPending} onClick={() => remove.mutate(doc.id, { onSuccess: () => navigate('/documents') })}>{remove.isPending ? 'Deleting…' : 'Delete it'}</Button>
            <Button variant="secondary" onClick={() => setConfirm(false)}>Keep it</Button>
          </div>
        </div>
      )}
      {failure && <p role="alert" className="mt-2 text-sm text-[var(--bad)]">{failure.message}</p>}

      {ready && inspecting && <InspectView doc={doc} initialPage={initialPage} improving={reprocess.isPending} onImprove={() => doc.next_tier && reprocess.mutate({ id: doc.id, tier: doc.next_tier })} />}
      {ready ? <DocumentTools doc={doc} /> : doc.state !== 'failed' && <p className="mt-4 text-sm text-[var(--muted)]">Reachy is still reading this document. You can ask, search and summarise once it is ready.</p>}
    </article>
  );
}
