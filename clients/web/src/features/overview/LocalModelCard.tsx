import { useQuery } from '@tanstack/react-query';
import { fetchLocalStats, type LocalMetrics } from '../../api/localStats';
import { EmptyState } from '../../components/shared/states';
import { Card } from '../../components/ui/Card';
import { Spinner } from '../../components/ui/Spinner';
import { StatusPill } from '../../components/ui/StatusPill';

export const LOCAL_STATS_POLL_MS = 5_000;

const count = (v: number | null) => (v === null ? '—' : Math.round(v).toLocaleString());
const percent = (v: number | null) => (v === null ? '—' : `${(v * 100).toFixed(1)}%`);
const seconds = (v: number | null) => (v === null ? '—' : v < 1 ? `${Math.round(v * 1000)} ms` : `${v.toFixed(2)} s`);

export function metricRows(m: LocalMetrics): [string, string][] {
  return [
    ['Requests running', count(m.requests_running)],
    ['Requests waiting', count(m.requests_waiting)],
    ['KV cache in use', percent(m.kv_cache_usage)],
    ['Prefix cache hit rate', percent(m.prefix_cache_hit_rate)],
    ['Mean time to first token', seconds(m.mean_time_to_first_token_s)],
    ['Mean request latency', seconds(m.mean_e2e_latency_s)],
    ['Requests finished', count(m.requests_finished_total)],
    ['Input tokens', count(m.prompt_tokens_total)],
    ['Output tokens', count(m.generation_tokens_total)],
    ['Preemptions', count(m.preemptions_total)],
  ];
}

// Counters are since the vLLM container last started, unlike the 24-hour usage cards beside it.
export function LocalModelCard() {
  const { data, error, isPending } = useQuery({
    queryKey: ['overview', 'local-stats'],
    queryFn: ({ signal }) => fetchLocalStats(signal),
    refetchInterval: LOCAL_STATS_POLL_MS,
    retry: false,
  });
  return (
    <Card eyebrow="SINCE CONTAINER START" title="Local model server (vLLM)">
      {isPending && <Spinner label="Loading local model stats" />}
      {error && <EmptyState>Local model stats unavailable — {error.message}</EmptyState>}
      {data?.status === 'not_configured' && <EmptyState>No local model is configured. Set one under Settings.</EmptyState>}
      {data?.status === 'unavailable' && (
        <p className="text-sm"><StatusPill tone="bad">Not responding</StatusPill> The vLLM server did not answer its health check.</p>
      )}
      {data?.status === 'ok' && (
        <div className="space-y-3 text-sm">
          <p className="flex flex-wrap items-center gap-2">
            <StatusPill tone="good">Healthy</StatusPill>
            {data.model && <span className="break-words">{data.model.id}{data.model.max_model_len ? ` · ${data.model.max_model_len.toLocaleString()} token context` : ''}</span>}
          </p>
          {data.metrics ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
              {metricRows(data.metrics).map(([label, value]) => (
                <div key={label} className="contents">
                  <dt className="text-[var(--muted)]">{label}</dt>
                  <dd className="text-right tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <EmptyState>The server is healthy but does not publish metrics.</EmptyState>
          )}
        </div>
      )}
    </Card>
  );
}
