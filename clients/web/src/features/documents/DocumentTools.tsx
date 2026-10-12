import { useState, type FormEvent } from 'react';
import { StaleSessionError } from '../../api/client';
import type { AnswerDto, DocumentDto, SearchDto, SummaryDto, SummaryStyle } from '../../api/documents';
import { Button } from '../../components/ui/Button';
import { Spinner } from '../../components/ui/Spinner';
import { StatusPill } from '../../components/ui/StatusPill';
import { useStatus } from '../overview/useStatus';
import { useDocumentActions, useSummaries } from './useDocuments';

const STYLES: { style: SummaryStyle; label: string }[] = [
  { style: 'ordinary', label: 'Summary' },
  { style: 'executive', label: 'Executive summary' },
  { style: 'technical', label: 'Technical summary' },
];
const STYLE_NAME: Record<SummaryStyle, string> = { ordinary: 'Summary', executive: 'Executive summary', technical: 'Technical summary' };
const WHY: Record<string, string> = {
  sparse_text: 'Very little text could be read from this document, so there is nothing reliable to summarise. Improve the reading above and try again.',
  no_local_model: 'No local language model is configured, so summaries are unavailable.',
  model_unavailable: 'The language model did not answer. Try again shortly.',
  worker_unavailable: 'The document service did not answer. Try again shortly.',
  interrupted: 'This summary was interrupted by a restart. Make it again.',
};

const message = (error: unknown) => (error && !(error instanceof StaleSessionError) ? (error as Error).message : '');

export function DocumentTools({ doc }: { doc: DocumentDto }) {
  return (
    <div className="mt-6 space-y-8 border-t border-[var(--border)] pt-4">
      <AskPanel doc={doc} />
      <SearchPanel doc={doc} />
      <SummariesPanel doc={doc} />
    </div>
  );
}

function AskPanel({ doc }: { doc: DocumentDto }) {
  const { ask } = useDocumentActions();
  const status = useStatus();
  const user = status.data?.defaultUserId ?? null;
  const [text, setText] = useState('');
  const [answer, setAnswer] = useState<AnswerDto | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || !user) return;
    ask.mutate({ user, id: doc.id, text: text.trim() }, { onSuccess: setAnswer });
  }
  return (
    <section aria-label="Ask about this document">
      <h3 className="font-medium">Ask about this document</h3>
      <form onSubmit={submit} className="mt-2 flex flex-wrap gap-2">
        <input
          aria-label="Your question"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={1000}
          placeholder="What does it say about…"
          className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--surface)] p-1.5"
        />
        <Button type="submit" disabled={ask.isPending || !text.trim() || !user}>{ask.isPending ? 'Reading…' : 'Ask'}</Button>
      </form>
      {message(ask.error) && <p role="alert" className="mt-2 text-sm text-[var(--bad)]">{message(ask.error)}</p>}
      {answer && (
        <div className="mt-3 rounded-md bg-[var(--hover)] p-3" aria-live="polite">
          <p className="whitespace-pre-wrap text-sm [overflow-wrap:anywhere]">{answer.reply}</p>
          {answer.citations.length > 0 && (
            <p className="mt-2 text-xs text-[var(--muted)]">
              From pages: {answer.citations.map((c) => c.page).join(', ')} of &ldquo;{answer.context_document ?? doc.title}&rdquo;. The answer is Reachy&apos;s wording; check the original for anything that matters.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function SearchPanel({ doc }: { doc: DocumentDto }) {
  const { search } = useDocumentActions();
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<SearchDto | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (query.trim()) search.mutate({ id: doc.id, query: query.trim() }, { onSuccess: setResult });
  }
  return (
    <section aria-label="Search this document">
      <h3 className="font-medium">Search this document</h3>
      <form onSubmit={submit} className="mt-2 flex flex-wrap gap-2">
        <input aria-label="Search words" value={query} onChange={(e) => setQuery(e.target.value)} maxLength={500} className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--surface)] p-1.5" />
        <Button type="submit" variant="secondary" disabled={search.isPending || !query.trim()}>Search</Button>
      </form>
      {message(search.error) && <p role="alert" className="mt-2 text-sm text-[var(--bad)]">{message(search.error)}</p>}
      {result && result.hits.length === 0 && <p className="mt-2 text-sm text-[var(--muted)]">Nothing found{result.complete ? '' : ' in the part searched'}.</p>}
      {result && result.hits.length > 0 && (
        <ul className="mt-2 space-y-2">
          {result.hits.map((hit, index) => (
            <li key={`${hit.locator ?? 'x'}-${index}`} className="rounded-md border border-[var(--border)] p-2 text-sm">
              <span className="mr-2 text-xs font-medium text-[var(--muted)]">{hit.page ? `Page ${hit.page}` : 'Page unknown'}</span>
              <span className="[overflow-wrap:anywhere]">{hit.snippet}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SummariesPanel({ doc }: { doc: DocumentDto }) {
  const summaries = useSummaries(doc.id);
  const { summarize } = useDocumentActions();
  const [chosen, setChosen] = useState<SummaryStyle | null>(null);
  const list = summaries.data ?? [];
  const has = (style: SummaryStyle) => list.some((s) => s.style === style);
  const running = new Set(list.filter((s) => s.status === 'running').map((s) => s.style));
  // The buttons choose which summary is shown. Before the owner chooses, the first one that exists is shown. A style with no summary yet is written when its button is pressed;
  // pressing the button of one that exists only shows it (the server returns a current summary as it is, so asking again would change nothing on screen).
  const shown = chosen ?? STYLES.find(({ style }) => has(style))?.style ?? null;
  const shownList = list.filter((s) => s.style === shown);
  const choose = (style: SummaryStyle) => {
    setChosen(style);
    if (!has(style)) summarize.mutate({ id: doc.id, style });
  };
  return (
    <section aria-label="Summaries">
      <h3 className="font-medium">Summaries</h3>
      <div role="group" aria-label="Summary style" className="mt-2 flex flex-wrap gap-2">
        {STYLES.map(({ style, label }) => (
          <Button
            key={style}
            variant="secondary"
            aria-pressed={shown === style}
            className={shown === style ? 'ring-2 ring-[var(--accent)]' : ''}
            disabled={summarize.isPending || running.has(style)}
            onClick={() => choose(style)}
          >
            {running.has(style) ? `${label}…` : has(style) ? label : `Write ${label.toLowerCase()}`}
          </Button>
        ))}
      </div>
      {message(summarize.error) && <p role="alert" className="mt-2 text-sm text-[var(--bad)]">{message(summarize.error)}</p>}
      {summaries.isPending && <Spinner label="Loading summaries" />}
      {!summaries.isPending && shown === null && <p className="mt-3 text-sm text-[var(--muted)]">No summary yet. Choose a style to have Reachy write one.</p>}
      {shown !== null && shownList.length === 0 && summarize.isPending && <p role="status" className="mt-3 text-sm text-[var(--muted)]">Starting the {STYLE_NAME[shown].toLowerCase()}…</p>}
      <ul className="mt-3 space-y-3">
        {shownList.map((s) => (
          <SummaryCard key={s.id} summary={s} onRedo={() => summarize.mutate({ id: doc.id, style: s.style, force: true })} busy={summarize.isPending} />
        ))}
      </ul>
    </section>
  );
}

function SummaryCard({ summary: s, onRedo, busy }: { summary: SummaryDto; onRedo: () => void; busy: boolean }) {
  return (
    <li className="rounded-lg border border-[var(--border)] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="font-medium">{STYLE_NAME[s.style]}</h4>
        {s.status === 'running' && <StatusPill tone="warn">Writing</StatusPill>}
        {s.status === 'failed' && <StatusPill tone="bad">Failed</StatusPill>}
        {s.status === 'ready' && (s.stale ? <StatusPill tone="warn">Out of date</StatusPill> : <StatusPill tone="good">Current</StatusPill>)}
        <span className="text-xs text-[var(--muted)]">
          Read at {s.tier}{s.pages_covered ? ` · pages ${s.pages_covered}` : ''}{s.page_count ? ` of ${s.page_count}` : ''}{s.model ? ` · ${s.model}` : ''}
        </span>
      </div>
      {s.truncated && <p className="mt-1 text-xs text-[var(--warn)]">This document is longer than Reachy summarises in one go; only pages {s.pages_covered} are covered.</p>}
      {s.status === 'failed' && <p className="mt-2 text-sm text-[var(--bad)]">{WHY[s.error_code ?? ''] ?? 'The summary could not be made.'}</p>}
      {s.status === 'ready' && (
        <>
          <p className="mt-2 whitespace-pre-wrap text-sm [overflow-wrap:anywhere]">{s.text}</p>
          {s.sections.length > 1 && (
            <details className="mt-2 text-sm">
              <summary className="cursor-pointer">Notes by page group ({s.sections.length})</summary>
              <ul className="mt-2 space-y-2">
                {s.sections.map((section) => (
                  <li key={section.pages}>
                    <span className="mr-2 text-xs font-medium text-[var(--muted)]">Pages {section.pages}</span>
                    <span className="whitespace-pre-wrap [overflow-wrap:anywhere]">{section.summary}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <p className="mt-2 text-xs text-[var(--muted)]">Written by a language model from a machine reading of the document; it can be wrong. Check the original for anything that matters.</p>
        </>
      )}
      {s.status !== 'running' && (s.stale || s.status === 'failed') && (
        <Button variant="secondary" className="mt-2" disabled={busy} onClick={onRedo}>Make it again</Button>
      )}
    </li>
  );
}
