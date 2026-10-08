import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { EmptyState, ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { useBloom } from '../../app/displayPrefs';
import { Check, selectClass } from '../settings/fields';
import { ALL_TYPES, SOURCE_COLOR, SOURCE_LABEL, SOURCE_TYPES, applyFilters, type BrainEdge, type BrainNode, type BrainSource, type SourceType } from './model';
import { createSyntheticSource } from './synthetic';
import { useBrainData } from './useBrainData';
import { PARTICLES, defaultDetail, prefersReducedMotion, webglAvailable, type Detail } from './webgl';

// The 3D code (three.js and friends) is a separate download, fetched only when the owner opens this page on a browser
// that can use it.
const BrainScene = lazy(() => import('./BrainScene'));

const LIST_LIMIT = 40;

export default function BrainPage({ source: given }: { source?: BrainSource }) {
  const source = useMemo(() => given ?? createSyntheticSource(), [given]);
  const data = useBrainData(source);
  const [query, setQuery] = useState('');
  const [types, setTypes] = useState<ReadonlySet<SourceType>>(ALL_TYPES);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showAllLinks, setShowAllLinks] = useState(false);
  const [resetToken, setResetToken] = useState(0);
  const [reducedMotion] = useState(prefersReducedMotion);
  const [bloom] = useBloom(); // changed under Settings · Display
  const [webgl] = useState(webglAvailable);
  const [detail, setDetail] = useState<Detail>(() => defaultDetail(window.innerWidth, prefersReducedMotion()));

  const nodes = data.data?.nodes ?? [];
  const edges = data.data?.edges ?? [];
  const matches = useMemo(() => applyFilters(nodes, { types, query }), [nodes, types, query]);
  const visible = useMemo(() => new Set(matches.map((n) => n.id)), [matches]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const selected = selectedId ? (byId.get(selectedId) ?? null) : null;
  // A selection that the filters now hide is dropped rather than left pointing at something off screen.
  useEffect(() => {
    if (selectedId && !visible.has(selectedId)) setSelectedId(null);
  }, [selectedId, visible]);

  const counts = data.data?.summary.byType ?? ({} as Record<SourceType, number>);
  const toggleType = (t: SourceType) => {
    const next = new Set(types);
    if (next.has(t)) next.delete(t);
    else next.add(t);
    setTypes(next);
  };

  return (
    <div>
      <div className="mb-3">
        <span className="block text-[0.7rem] font-medium tracking-widest text-[var(--muted)]">KNOWLEDGE</span>
        <h1 className="text-2xl font-semibold">Brain</h1>
      </div>
      <p role="note" className="mb-3 rounded border border-[var(--warn)] bg-[var(--warn-bg)] p-2 text-sm text-[var(--warn)]">
        <strong>{source.label}.</strong> {source.kind === 'synthetic' ? 'These records are generated for this demonstration and stand for none of Reachy’s real memories, documents, meetings, notes, tasks or reminders. Nothing here is read from your data.' : ''}
      </p>
      {data.isPending && <p role="status" className="text-[var(--muted)]">Loading…</p>}
      {data.error && <ErrorState message={data.error.message} onRetry={() => void data.refetch()} />}
      {data.data && (
        <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
          <div className="min-w-0">
            <div className="relative h-[26rem] overflow-hidden rounded-lg border border-[var(--border)] bg-[#05070d] sm:h-[32rem]" data-testid="brain-view">
              {webgl ? (
                <Suspense fallback={<p role="status" className="p-4 text-sm text-[#9aa4b2]">Loading the 3D view…</p>}>
                  <div role="img" aria-label={`3D view of ${matches.length} of ${nodes.length} synthetic records in six groups. The list beside it offers the same records for keyboard and screen reader use.`} className="h-full w-full" data-testid="brain-canvas">
                    <BrainScene
                      nodes={nodes}
                      edges={edges}
                      visible={visible}
                      counts={counts}
                      selectedId={selectedId}
                      particleCount={PARTICLES[detail]}
                      showAllLinks={showAllLinks}
                      bloom={bloom}
                      reducedMotion={reducedMotion}
                      resetToken={resetToken}
                      onSelect={setSelectedId}
                    />
                  </div>
                </Suspense>
              ) : (
                <p role="status" className="p-4 text-sm text-[#cbd5e1]" data-testid="brain-fallback">
                  3D graphics are not available in this browser, so the records are shown as a list instead.
                </p>
              )}
            </div>
            <p className="mt-2 text-xs text-[var(--muted)]">
              Glowing dots are records, grouped by kind; lines are explicit links; the faint haze is decoration with no record behind it. Distance between dots means nothing beyond grouping.
            </p>
          </div>

          <aside className="space-y-3" aria-label="Brain controls">
            <label className="block text-sm">
              Search records
              <input type="search" className={selectClass} placeholder="Title, text or kind" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            <fieldset>
              <legend className="mb-1 text-sm font-medium">Kinds</legend>
              {SOURCE_TYPES.map((t) => (
                <label key={t} className="mb-1 flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={types.has(t)} onChange={() => toggleType(t)} />
                  <span aria-hidden="true" className="inline-block h-3 w-3 rounded-full" style={{ background: SOURCE_COLOR[t] }} />
                  {SOURCE_LABEL[t]} <span className="text-[var(--muted)]">{counts[t] ?? 0}</span>
                </label>
              ))}
            </fieldset>
            <p role="status" className="text-sm text-[var(--muted)]">
              {`Showing ${matches.length} of ${nodes.length} records · ${edges.length} explicit links · ${webgl ? PARTICLES[detail].toLocaleString() : 0} decorative particles (not records)${data.data.truncated ? ' · more records exist than this view loads' : ''}`}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="secondary" onClick={() => setResetToken((n) => n + 1)}>Reset view</Button>
              <Check label="Show all links" checked={showAllLinks} onChange={setShowAllLinks} />
            </div>
            {webgl && (
              <label className="block text-sm">
                Detail
                <select aria-label="Detail" className={selectClass} value={detail} onChange={(e) => setDetail(e.target.value as Detail)}>
                  <option value="low">Low (lighter on weak hardware)</option>
                  <option value="normal">Normal</option>
                  <option value="high">High</option>
                </select>
              </label>
            )}
            <RecordList matches={matches} selectedId={selectedId} onSelect={setSelectedId} />
            <DetailsPanel
              node={selected}
              edges={edges}
              byId={byId}
              onSelect={(id) => {
                // Following a link to a record the filters hide clears the filters, so the destination is visible.
                if (!visible.has(id)) {
                  setQuery('');
                  setTypes(ALL_TYPES);
                }
                setSelectedId(id);
              }}
            />
            <section aria-label="Relationships and activity" className="rounded border border-[var(--border)] p-2 text-sm text-[var(--muted)]">
              <h3 className="font-medium text-[var(--text)]">Not available yet</h3>
              <p>Inferred, reviewed and disputed relationships, and a feed of real knowledge activity, need parts of the knowledge system that do not exist yet. They are not simulated here.</p>
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}

function RecordList({ matches, selectedId, onSelect }: { matches: BrainNode[]; selectedId: string | null; onSelect(id: string): void }) {
  return (
    <section aria-label="Records">
      <h3 className="mb-1 text-sm font-medium">Records</h3>
      {matches.length === 0 && <EmptyState>No records match.</EmptyState>}
      <ul className="max-h-64 overflow-y-auto text-sm">
        {matches.slice(0, LIST_LIMIT).map((n) => (
          <li key={n.id}>
            <button
              type="button"
              aria-pressed={n.id === selectedId}
              className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left hover:bg-[var(--hover)] ${n.id === selectedId ? 'bg-[var(--hover)]' : ''}`}
              onClick={() => onSelect(n.id)}
            >
              <span aria-hidden="true" className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SOURCE_COLOR[n.type] }} />
              <span className="break-words">{n.title}</span>
            </button>
          </li>
        ))}
      </ul>
      {matches.length > LIST_LIMIT && <p className="text-xs text-[var(--muted)]">{`${matches.length - LIST_LIMIT} more — narrow the search to see them.`}</p>}
    </section>
  );
}

function DetailsPanel({ node, edges, byId, onSelect }: { node: BrainNode | null; edges: BrainEdge[]; byId: Map<string, BrainNode>; onSelect(id: string): void }) {
  if (!node) {
    return (
      <section aria-label="Record details" className="rounded border border-[var(--border)] p-2 text-sm text-[var(--muted)]">
        Select a record in the list or the 3D view to see where it comes from.
      </section>
    );
  }
  const links = edges.filter((e) => e.from === node.id || e.to === node.id);
  return (
    <section aria-label="Record details" className="rounded border border-[var(--border)] p-2 text-sm">
      <h3 className="break-words font-semibold">{node.title}</h3>
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1">
        <dt className="text-[var(--muted)]">Kind</dt>
        <dd>{SOURCE_LABEL[node.type]}</dd>
        <dt className="text-[var(--muted)]">Observed</dt>
        <dd>{new Date(node.observedAt).toLocaleDateString()}</dd>
        <dt className="text-[var(--muted)]">Source</dt>
        <dd className="break-all">{`${node.sourceRef.kind}:${node.sourceRef.id}`}</dd>
        <dt className="text-[var(--muted)]">Classification</dt>
        <dd>{node.sensitivity}</dd>
      </dl>
      <p className="mt-2 break-words">{node.excerpt}</p>
      <h4 className="mt-2 font-medium">Connected records</h4>
      {links.length === 0 && <p className="text-[var(--muted)]">No explicit links.</p>}
      <ul>
        {links.map((e) => {
          const otherId = e.from === node.id ? e.to : e.from;
          const other = byId.get(otherId);
          return (
            <li key={e.id} className="py-1">
              {other ? (
                <button type="button" className="break-words text-left underline" onClick={() => onSelect(other.id)}>{other.title}</button>
              ) : (
                <span className="text-[var(--muted)]">A record that is not loaded</span>
              )}
              <span className="block text-xs text-[var(--muted)]">{`Explicit link · ${e.basis}`}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
