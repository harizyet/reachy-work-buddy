import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { StaleSessionError } from '../../api/client';
import { getExport, getInspectPage, getOriginal, getPageImage, type BlockDto, type DocumentDto, type ExportKind, type InspectPageDto } from '../../api/documents';
import { Button } from '../../components/ui/Button';
import { Spinner } from '../../components/ui/Spinner';
import { StatusPill } from '../../components/ui/StatusPill';
import { saveBlob } from '../../utils/download';

type Tab = 'rendered' | 'markdown' | 'blocks';
const TIER: Record<string, string> = { flash: 'Flash', basic: 'Basic', standard: 'Standard', advanced: 'Advanced' };
const EXPORTS: { kind: ExportKind; label: string; ext: string }[] = [
  { kind: 'markdown', label: 'Markdown', ext: 'md' },
  { kind: 'html', label: 'HTML', ext: 'html' },
  { kind: 'content_list', label: 'Content list (JSON)', ext: 'json' },
  { kind: 'middle_json', label: 'Structured result (JSON)', ext: 'json' },
];

// The right-hand pane shows MinerU's own HTML for the page. It is document-derived text, so it only ever goes into a sandboxed frame: no scripts, no same-origin access, no network.
const FRAME_POLICY = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">`;
const safeName = (value: string) => value.replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^[._]+|[._]+$/g, '').slice(0, 60) || 'document';

/** An image fetched with the signed-in session and shown through a temporary object URL (a plain <img src> would not carry the session). */
function useImage(key: readonly unknown[], load: (signal: AbortSignal) => Promise<Blob>, enabled: boolean) {
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => load(signal), enabled, staleTime: 5 * 60_000, retry: false });
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!query.data) {
      setUrl(null);
      return;
    }
    const made = URL.createObjectURL(query.data);
    setUrl(made);
    return () => URL.revokeObjectURL(made);
  }, [query.data]);
  return { url, pending: query.isPending && enabled, failed: query.isError };
}

export function InspectView({ doc, onImprove, improving }: { doc: DocumentDto; onImprove: () => void; improving: boolean }) {
  const [page, setPage] = useState(1);
  const [tab, setTab] = useState<Tab>('rendered');
  const [overlay, setOverlay] = useState(true);
  const [selected, setSelected] = useState<number | null>(null);
  const [saving, setSaving] = useState('');
  const [saveError, setSaveError] = useState('');

  const view = useQuery({
    queryKey: ['documents', 'inspect', doc.id, page, doc.tier, doc.updated_at],
    queryFn: ({ signal }) => getInspectPage(doc.id, page, signal),
    retry: false,
    placeholderData: (previous) => previous,
  });
  const data: InspectPageDto | undefined = view.data;
  const pageCount = data?.page_count ?? doc.page_count ?? 1;
  const hasImage = data?.page_image ?? false;
  const picture = useImage(['documents', 'page-image', doc.id, page, doc.tier, doc.updated_at], (signal) => getPageImage(doc.id, page, undefined, signal), hasImage);
  const crop = useImage(['documents', 'block-image', doc.id, page, selected, doc.tier, doc.updated_at], (signal) => getPageImage(doc.id, page, selected!, signal), hasImage && selected !== null);

  useEffect(() => setSelected(null), [page]);

  const go = (next: number) => setPage(Math.min(Math.max(1, next), pageCount));
  const save = async (label: string, ext: string, load: () => Promise<Blob>) => {
    setSaving(label);
    setSaveError('');
    try {
      saveBlob(await load(), `${safeName(doc.title)}-${doc.tier ?? 'original'}-${label}.${ext}`);
    } catch (error) {
      if (!(error instanceof StaleSessionError)) setSaveError(error instanceof Error ? error.message : 'The download failed');
    } finally {
      setSaving('');
    }
  };
  const selectedBlock: BlockDto | undefined = data?.blocks.find((b) => b.block === selected);
  const reading = doc.state === 'queued' || doc.state === 'processing' || doc.state === 'uploaded';

  return (
    <section aria-label="Extraction inspector" className="mt-6 border-t border-[var(--border)] pt-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h3 className="font-medium">Extraction inspector</h3>
        <StatusPill tone={doc.state === 'ready' ? 'good' : doc.state === 'failed' ? 'bad' : 'warn'}>{doc.state === 'ready' ? 'Ready' : doc.state === 'failed' ? 'Failed' : 'Reading'}</StatusPill>
        <span className="text-sm text-[var(--muted)]">Read at {doc.tier ? TIER[doc.tier] : 'unknown level'}</span>
        {doc.next_tier && (
          <Button variant="secondary" disabled={improving || reading} onClick={onImprove}>
            Improve reading ({TIER[doc.next_tier]}{doc.next_tier === 'advanced' ? ', very slow' : ''})
          </Button>
        )}
      </div>
      <p className="mt-1 text-xs text-[var(--muted)]">
        This is what MinerU, the reader, extracted from the original. It is a machine&apos;s reading and can be wrong; the original is what counts. Compare the two here and read again at a higher level if the text came out badly.
      </p>
      {reading && <p role="status" className="mt-2 text-sm text-[var(--warn)]">Reading again… this view updates when it finishes.</p>}

      <div className="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="Page navigation">
        <Button variant="secondary" disabled={page <= 1} onClick={() => go(page - 1)} aria-label="Previous page">&larr; Previous</Button>
        <label className="text-sm">
          Page{' '}
          <input
            type="number"
            min={1}
            max={pageCount}
            value={page}
            onChange={(e) => go(Number(e.target.value) || 1)}
            aria-label="Page number"
            className="w-16 rounded-md border border-[var(--border)] bg-[var(--surface)] p-1"
          />{' '}
          of {pageCount}
        </label>
        <Button variant="secondary" disabled={page >= pageCount} onClick={() => go(page + 1)} aria-label="Next page">Next &rarr;</Button>
        {hasImage && (
          <label className="ml-2 text-sm">
            <input type="checkbox" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} className="mr-1" />
            Show blocks on the page
          </label>
        )}
      </div>

      {view.isPending && <Spinner label="Loading the extraction" />}
      {view.error && !data && <p role="alert" className="mt-3 text-sm text-[var(--bad)]">{view.error.message}</p>}

      {data && (
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <div aria-label="Original page">
            <h4 className="mb-1 text-sm font-medium">Original, page {data.page}</h4>
            {!hasImage && <p className="rounded-md border border-[var(--border)] p-3 text-sm text-[var(--muted)]">There is no page picture for this kind of file. The extraction is on the right; download the original below to see it as it is.</p>}
            {hasImage && picture.pending && <Spinner label="Drawing the page" />}
            {hasImage && picture.failed && <p role="alert" className="text-sm text-[var(--bad)]">The page picture could not be drawn.</p>}
            {picture.url && (
              <div className="relative inline-block max-w-full overflow-hidden rounded-md border border-[var(--border)]">
                <img src={picture.url} alt={`Page ${data.page} of ${data.title}, as in the original`} className="block h-auto max-w-full" />
                {overlay &&
                  data.blocks
                    .filter((b) => b.bbox)
                    .map((b) => {
                      const [l, t, r, bt] = b.bbox!;
                      return (
                        <button
                          key={b.block}
                          type="button"
                          aria-label={`Block ${b.block}, ${b.type}`}
                          aria-pressed={selected === b.block}
                          title={`Block ${b.block}: ${b.type}`}
                          onClick={() => setSelected(selected === b.block ? null : b.block)}
                          style={{ position: 'absolute', left: `${l * 100}%`, top: `${t * 100}%`, width: `${(r - l) * 100}%`, height: `${(bt - t) * 100}%` }}
                          className={`border-2 ${selected === b.block ? 'border-[var(--accent)] bg-[var(--accent)]/20' : 'border-[var(--accent)]/60 hover:bg-[var(--accent)]/10'}`}
                        />
                      );
                    })}
              </div>
            )}
            {selectedBlock && (
              <div className="mt-2 rounded-md border border-[var(--border)] p-2 text-sm" aria-label="Selected block">
                <p>Block {selectedBlock.block}: {selectedBlock.type}</p>
                {crop.pending && <Spinner label="Cutting out the block" />}
                {crop.url && <img src={crop.url} alt={`Block ${selectedBlock.block} (${selectedBlock.type}) cut from the page`} className="mt-1 max-h-60 max-w-full rounded border border-[var(--border)]" />}
                {crop.failed && <p className="text-[var(--muted)]">No picture is available for this block.</p>}
              </div>
            )}
          </div>

          <div aria-label="Extracted output">
            <div role="tablist" aria-label="Extraction views" className="mb-2 flex gap-1">
              {(['rendered', 'markdown', 'blocks'] as Tab[]).map((id) => (
                <button
                  key={id}
                  role="tab"
                  type="button"
                  aria-selected={tab === id}
                  onClick={() => setTab(id)}
                  className={`rounded-md px-3 py-1 text-sm ${tab === id ? 'bg-[var(--accent)] text-white' : 'border border-[var(--border)] hover:bg-[var(--hover)]'}`}
                >
                  {id === 'rendered' ? 'Rendered' : id === 'markdown' ? 'Markdown' : `Blocks (${data.blocks.length})`}
                </button>
              ))}
            </div>
            {tab === 'rendered' && (
              <>
                <iframe
                  title={`Extracted page ${data.page}, rendered by MinerU`}
                  sandbox=""
                  referrerPolicy="no-referrer"
                  srcDoc={`${FRAME_POLICY}${data.html}`}
                  className="h-[32rem] w-full rounded-md border border-[var(--border)] bg-white"
                />
                <p className="mt-1 text-xs text-[var(--muted)]">Shown in a locked frame. Formulas appear as LaTeX source and figures as their captions; select a block on the page to see its picture.</p>
              </>
            )}
            {tab === 'markdown' && <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-md border border-[var(--border)] bg-[var(--surface)] p-3 text-xs [overflow-wrap:anywhere]">{data.markdown}</pre>}
            {tab === 'blocks' && (
              <div className="max-h-[32rem] overflow-auto">
                <table className="w-full text-left text-xs">
                  <caption className="sr-only">Blocks MinerU found on page {data.page}</caption>
                  <thead>
                    <tr className="border-b border-[var(--border)]"><th className="p-1">#</th><th className="p-1">Type</th><th className="p-1">Position (% of page)</th></tr>
                  </thead>
                  <tbody>
                    {data.blocks.map((b) => (
                      <tr key={b.block} className={`border-b border-[var(--border)] ${selected === b.block ? 'bg-[var(--hover)]' : ''}`}>
                        <td className="p-1">{b.block}</td>
                        <td className="p-1">{b.type}</td>
                        <td className="p-1">{b.bbox ? `${Math.round(b.bbox[0] * 100)}–${Math.round(b.bbox[2] * 100)} across, ${Math.round(b.bbox[1] * 100)}–${Math.round(b.bbox[3] * 100)} down` : 'not given'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="mt-4" role="group" aria-label="Downloads">
        <h4 className="text-sm font-medium">Download</h4>
        <div className="mt-1 flex flex-wrap gap-2">
          {EXPORTS.map((e) => (
            <Button key={e.kind} variant="secondary" disabled={saving !== ''} onClick={() => void save(e.kind, e.ext, () => getExport(doc.id, e.kind))}>{saving === e.kind ? 'Preparing…' : e.label}</Button>
          ))}
          <Button variant="secondary" disabled={saving !== ''} onClick={() => void save('original', doc.filename.split('.').pop() ?? 'bin', () => getOriginal(doc.id))}>{saving === 'original' ? 'Preparing…' : 'Original file'}</Button>
        </div>
        {saveError && <p role="alert" className="mt-2 text-sm text-[var(--bad)]">{saveError}</p>}
      </div>
    </section>
  );
}
