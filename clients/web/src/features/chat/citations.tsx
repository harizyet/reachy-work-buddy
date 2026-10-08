import type { ReactNode } from 'react';
import type { SearchSource, WebSearch } from '../../api/types';

// Only plain http(s) links without credentials are ever made clickable; anything else stays literal text.
export function safeUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    return ['https:', 'http:'].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : null;
  } catch {
    return null;
  }
}

function ExternalLink({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className ?? 'underline'}>
      {children}
    </a>
  );
}

/** The model cites sources as [S1], [S2]: each becomes a link to that result; unknown ids stay plain text. */
export function withCitations(text: string, results: SearchSource[]): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(/\[S(\d+)\]/g)) {
    out.push(text.slice(last, match.index));
    const url = safeUrl(results[Number(match[1]) - 1]?.url ?? '');
    out.push(url ? <ExternalLink key={match.index} href={url} className="font-medium text-[var(--accent)] underline">{match[0]}</ExternalLink> : match[0]);
    last = match.index + match[0].length;
  }
  out.push(text.slice(last));
  return out;
}

export function SourcesList({ results }: { results: SearchSource[] }) {
  return (
    <div className="mt-2 text-sm">
      <strong>Sources</strong>
      <ol className="ml-5 list-decimal">
        {results.map((r, i) => {
          const label = `[S${i + 1}] ${r.source_domain ? r.source_domain + ': ' : ''}${r.title || r.url}`;
          const url = safeUrl(r.url);
          return <li key={i}>{url ? <ExternalLink href={url}>{label}</ExternalLink> : label}</li>;
        })}
      </ol>
    </div>
  );
}

export function SearchDetails({ search }: { search: WebSearch }) {
  return (
    <details className="mt-2 rounded border border-[var(--border)] p-2 text-sm">
      <summary className="cursor-pointer">
        {search.failed ? 'Web search unavailable' : `Web search · ${search.results.length} results`}
      </summary>
      <p className="mt-1">{`Searched: ${search.query}`}</p>
      {(search.failed || search.results.length === 0) && (
        <p>{search.failed ? 'The search failed. No results were available for this reply.' : 'No results were found.'}</p>
      )}
      <ol className="ml-5 list-decimal">
        {search.results.map((r, i) => {
          const url = safeUrl(r.url);
          const title = `[S${i + 1}] ${r.title || r.source_domain || r.url}`;
          return (
            <li key={i}>
              {url ? <ExternalLink href={url}>{title}</ExternalLink> : <span>{title}</span>} <small className="text-[var(--muted)]">{r.source_domain}</small>
              <p>{r.snippet}</p>
            </li>
          );
        })}
      </ol>
    </details>
  );
}
