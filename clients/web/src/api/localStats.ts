import { ApiShapeError, request } from './client';

// Live vLLM numbers from GET /llm/local-stats (companion core reads vLLM's /health, /v1/models and /metrics).
export interface LocalMetrics {
  requests_running: number | null;
  requests_waiting: number | null;
  kv_cache_usage: number | null;
  prompt_tokens_total: number | null;
  generation_tokens_total: number | null;
  requests_finished_total: number | null;
  preemptions_total: number | null;
  mean_time_to_first_token_s: number | null;
  mean_e2e_latency_s: number | null;
  prefix_cache_hit_rate: number | null;
}

export type LocalStats =
  | { status: 'not_configured' | 'unavailable' }
  | { status: 'ok'; model: { id: string; max_model_len: number | null } | null; metrics: LocalMetrics | null };

const METRIC_KEYS: (keyof LocalMetrics)[] = [
  'requests_running', 'requests_waiting', 'kv_cache_usage', 'prompt_tokens_total', 'generation_tokens_total',
  'requests_finished_total', 'preemptions_total', 'mean_time_to_first_token_s', 'mean_e2e_latency_s', 'prefix_cache_hit_rate',
];

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const optNum = (v: unknown, what: string): number | null => {
  if (v === null || v === undefined) return null;
  if (typeof v !== 'number' || !Number.isFinite(v)) throw new ApiShapeError(what);
  return v;
};

export function parseLocalStats(value: unknown): LocalStats {
  if (!isObj(value)) throw new ApiShapeError('local-stats');
  if (value.status === 'not_configured' || value.status === 'unavailable') return { status: value.status };
  if (value.status !== 'ok') throw new ApiShapeError('local-stats.status');
  let model: { id: string; max_model_len: number | null } | null = null;
  if (isObj(value.model)) {
    if (typeof value.model.id !== 'string') throw new ApiShapeError('local-stats.model.id');
    model = { id: value.model.id, max_model_len: optNum(value.model.max_model_len, 'local-stats.model.max_model_len') };
  }
  let metrics: LocalMetrics | null = null;
  if (isObj(value.metrics)) {
    const raw = value.metrics;
    metrics = Object.fromEntries(METRIC_KEYS.map((k) => [k, optNum(raw[k], `local-stats.metrics.${k}`)])) as unknown as LocalMetrics;
  }
  return { status: 'ok', model, metrics };
}

export async function fetchLocalStats(signal?: AbortSignal): Promise<LocalStats> {
  return parseLocalStats(await request('/llm/local-stats', { signal }));
}
