import { useState, type FormEvent } from 'react';
import { StaleSessionError } from '../../api/client';
import type { SearchLog, SearchLogEntry, SearchUsage, WebSearchConfig } from '../../api/types';
import { useNotice } from '../../components/shared/notice';
import { ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Dialog } from '../../components/ui/Dialog';
import { Spinner } from '../../components/ui/Spinner';
import { safeUrl } from '../chat/citations';
import { Check, Field, SecretField, TextField, selectClass } from './fields';
import { useSaveWebSearch, useSearchLog, useWebSearch } from './useSettings';

const HOSTED = ['brave', 'exa', 'tavily'] as const;
const LABEL: Record<string, string> = { brave: 'Brave Search API', exa: 'Exa', tavily: 'Tavily' };

export function SearchTab() {
  const config = useWebSearch();
  const [logOpen, setLogOpen] = useState(false);
  const [saves, setSaves] = useState(0); // a save always resets the form, so typed keys never linger
  return (
    <div className="space-y-4">
      <Card eyebrow="GROUNDING" title="Web search">
        <p className="mb-2 text-sm">
          Lets the model check a live search when a question needs current or external information instead of guessing from training data. Off by default.
        </p>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Hosted providers (Brave, Exa, Tavily) receive each query directly. Each search goes to whichever enabled one has used the smallest share of its monthly limit. Reachy stops calling a provider when it reaches its limit, so keep limits below each free tier (Brave bills the card on file after its monthly credit). SearXNG runs only after every hosted provider failed or hit its limit. A self-hosted SearXNG instance still forwards your query to whichever upstream search engines it's configured to use, so this isn't full network confinement.
        </p>
        {config.isPending && <Spinner label="Loading web search settings" />}
        {config.error && !config.data && <ErrorState message={config.error.message} onRetry={() => void config.refetch()} />}
        {config.data && <SearchForm key={`${saves}|${JSON.stringify(config.data)}`} initial={config.data} onSaved={() => setSaves((n) => n + 1)} />}
      </Card>
      <UsageCard onOpenLog={() => setLogOpen(true)} />
      <Dialog open={logOpen} title="Web search log" onClose={() => setLogOpen(false)}>
        {logOpen && <LogView onClose={() => setLogOpen(false)} />}
      </Dialog>
    </div>
  );
}

function SearchForm({ initial, onSaved }: { initial: WebSearchConfig; onSaved: () => void }) {
  const save = useSaveWebSearch();
  const { setNotice } = useNotice();
  const [policy, setPolicy] = useState(initial.policy);
  const [fallback, setFallback] = useState(initial.fallback);
  const [baseUrl, setBaseUrl] = useState(initial.base_url ?? '');
  const [count, setCount] = useState(String(initial.result_count));
  const [key, setKey] = useState('');
  const [removeKey, setRemoveKey] = useState(false);
  const [hosted, setHosted] = useState(() =>
    Object.fromEntries(HOSTED.map((n) => [n, { enabled: !!initial.hosted[n]?.enabled, key: '', remove: false, limit: String(initial.hosted[n]?.monthly_limit ?? '') }])),
  );
  const set = (name: string, patch: Partial<(typeof hosted)[string]>) => setHosted({ ...hosted, [name]: { ...hosted[name]!, ...patch } });

  function submit(event: FormEvent) {
    event.preventDefault();
    const hostedBody: Record<string, Record<string, unknown>> = {};
    for (const name of HOSTED) {
      const h = hosted[name]!;
      hostedBody[name] = { enabled: h.enabled };
      const limit = Number(h.limit);
      if (limit) hostedBody[name]!.monthly_limit = limit;
      if (h.remove) hostedBody[name]!.api_key = null;
      else if (h.key) hostedBody[name]!.api_key = h.key;
    }
    // Only External SearXNG carries a base URL and key; the built-in one is found by the core itself.
    const patch: Record<string, unknown> = { policy, hosted: hostedBody, fallback, base_url: fallback === 'searxng' ? baseUrl.trim() : null, result_count: Number(count) || 5 };
    if (fallback !== 'searxng' || removeKey) patch.api_key = null;
    else if (key) patch.api_key = key;
    save.mutate(patch, { onSuccess: () => (setNotice('Web search settings saved.'), onSaved()) });
  }

  return (
    <form onSubmit={submit}>
      <Field label="Policy">
        <select className={selectClass} value={policy} onChange={(e) => setPolicy(e.target.value)}>
          <option value="off">Off — never search</option>
          <option value="auto">Auto — only when a question looks like it needs current info</option>
          <option value="always">Always — every message</option>
        </select>
      </Field>
      {HOSTED.map((name) => {
        const h = hosted[name]!;
        const used = initial.usage?.used[name];
        return (
          <fieldset key={name} className="mb-3 rounded border border-[var(--border)] p-3">
            <legend className="px-1 text-sm font-medium">{LABEL[name]}</legend>
            <Check label="Use in rotation" checked={h.enabled} onChange={(enabled) => set(name, { enabled })} />
            <SecretField label="API key" saved={initial.hosted[name]?.api_key ?? null} value={h.key} onValue={(v) => set(name, { key: v })} remove={h.remove} onRemove={(v) => set(name, { remove: v })} />
            <TextField label="Monthly search limit" type="number" min={1} max={1000000} value={h.limit} onChange={(e) => set(name, { limit: e.target.value })} />
            {used !== undefined && <small className="text-[var(--muted)]">{`Used ${used} of ${initial.hosted[name]?.monthly_limit} in ${initial.usage?.period} (UTC)`}</small>}
          </fieldset>
        );
      })}
      <Field label="Last-resort fallback">
        <select className={selectClass} value={fallback} onChange={(e) => setFallback(e.target.value)}>
          <option value="builtin_searxng">Built-in SearXNG (no setup needed)</option>
          <option value="searxng">External SearXNG</option>
          <option value="none">None</option>
        </select>
      </Field>
      {fallback === 'searxng' && (
        <>
          <TextField label="Base URL" type="url" placeholder="http://searxng-host:8080" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          <SecretField label="API key" optional saved={initial.api_key} value={key} onValue={setKey} remove={removeKey} onRemove={setRemoveKey} />
        </>
      )}
      <TextField label="Results per search" type="number" min={1} max={10} value={count} onChange={(e) => setCount(e.target.value)} />
      {save.error && !(save.error instanceof StaleSessionError) && <p role="alert" className="mb-2 text-sm text-[var(--bad)]">{save.error.message}</p>}
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          Save web search
        </Button>
        <Button variant="secondary" disabled={save.isPending} onClick={() => save.mutate({ policy: 'off' }, { onSuccess: () => (setNotice('Web search turned off.'), onSaved()) })}>
          Turn off web search
        </Button>
      </div>
    </form>
  );
}

function Meters({ usage }: { usage: SearchUsage | null }) {
  return (
    <div>
      <p className="mb-1 text-sm text-[var(--muted)]">{usage?.period ? `This month (${usage.period}, UTC)` : 'No usage data'}</p>
      {HOSTED.map((name) => {
        const used = usage?.used[name] ?? 0;
        const limit = usage?.limits[name] ?? 0;
        return (
          <div key={name} className="flex items-center gap-2 py-1 text-sm">
            <span className="w-24">{name + (usage?.enabled[name] ? '' : ' (off)')}</span>
            <meter className="flex-1" min={0} max={limit || 1} value={used} high={(limit || 1) * 0.8} />
            <small>{`${used} / ${limit}`}</small>
          </div>
        );
      })}
    </div>
  );
}

function UsageCard({ onOpenLog }: { onOpenLog: () => void }) {
  const log = useSearchLog(true);
  return (
    <Card eyebrow="GROUNDING" title="Search API usage">
      {log.isPending && <Spinner label="Loading usage" />}
      {log.error && !log.data && <p className="text-sm text-[var(--bad)]">{log.error.message}</p>}
      {log.data && <Meters usage={log.data.usage} />}
      <Button variant="secondary" className="mt-2" onClick={onOpenLog}>
        Open search debug log
      </Button>
    </Card>
  );
}

function Entry({ entry }: { entry: SearchLogEntry }) {
  return (
    <article className="border-b border-[var(--border)] py-2 text-sm">
      <p>{`${new Date(entry.at).toLocaleString()} · ${entry.served_by ? 'served by ' + entry.served_by : 'FAILED'} · ${entry.total_ms} ms · policy ${entry.policy}`}</p>
      <p>
        Query: <strong>{entry.query}</strong>
      </p>
      <small>{'Attempts: ' + (entry.attempts.map((a) => `${a.provider} ${a.outcome} (${a.ms} ms)`).join(' → ') || 'none')}</small>
      <ol className="ml-5 list-decimal">
        {entry.results.map((r, i) => {
          const url = safeUrl(r.url);
          return (
            <li key={i}>
              {url ? <a href={url} target="_blank" rel="noopener noreferrer" className="underline">{r.title}</a> : <span>{r.title}</span>} <small>{r.source_domain}</small>
              <p className="text-[var(--muted)]">{r.snippet}</p>
            </li>
          );
        })}
        {entry.results.length === 0 && <li>No results</li>}
      </ol>
    </article>
  );
}

function LogView({ onClose }: { onClose: () => void }) {
  const log = useSearchLog(true);
  const data: SearchLog | undefined = log.data;
  return (
    <div>
      <h2 className="mb-2 text-lg font-semibold">Web search log</h2>
      {log.isPending && <Spinner label="Loading" />}
      {log.error && !data && <p role="alert" className="text-sm text-[var(--bad)]">{log.error.message}</p>}
      {data && <Meters usage={data.usage} />}
      <div className="my-2 max-h-80 overflow-y-auto">
        {data && data.entries.length === 0 && <p className="text-sm">No searches since Companion Core started.</p>}
        {data?.entries.map((e, i) => <Entry key={i} entry={e} />)}
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={() => void log.refetch()}>
          Refresh
        </Button>
        <Button onClick={onClose}>Close</Button>
      </div>
    </div>
  );
}
