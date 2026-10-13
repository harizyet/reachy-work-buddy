import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { parseLocalStats } from '../src/api/localStats';
import { json, renderApp, SAMPLE_STATUS, stubHub } from './helpers';

const OK = {
  status: 'ok',
  model: { id: 'reachy-local', max_model_len: 8192 },
  metrics: {
    requests_running: 2, requests_waiting: 1, kv_cache_usage: 0.256, prompt_tokens_total: 12345, generation_tokens_total: 400,
    requests_finished_total: 8, preemptions_total: null, mean_time_to_first_token_s: 0.5, mean_e2e_latency_s: 2.5, prefix_cache_hit_rate: 0.25,
  },
};

const hub = (stats: () => Response) => ({ '/auth/me': () => json({ username: 'owner' }), '/status': () => json(SAMPLE_STATUS), '/websearch/log': () => json({ usage: null, entries: [] }), '/llm/local-stats': stats });

describe('Local model card', () => {
  it('shows health, model and formatted metrics, with missing values as dashes', async () => {
    stubHub(hub(() => json(OK)));
    renderApp('#/system');
    const card = within(await screen.findByRole('region', { name: 'Local model server (vLLM)' }));
    expect(await card.findByText('Healthy')).toBeInTheDocument();
    expect(card.getByText('reachy-local · 8,192 token context')).toBeInTheDocument();
    expect(card.getByText('25.6%')).toBeInTheDocument();
    expect(card.getByText('500 ms')).toBeInTheDocument();
    expect(card.getByText('2.50 s')).toBeInTheDocument();
    expect(card.getByText('12,345')).toBeInTheDocument();
    expect(card.getByText('Preemptions').nextElementSibling).toHaveTextContent('—');
  });

  it('says when the server is down, unconfigured or the request fails', async () => {
    stubHub(hub(() => json({ status: 'unavailable' })));
    const first = renderApp('#/system');
    expect(await screen.findByText('Not responding')).toBeInTheDocument();
    first.unmount();
    stubHub(hub(() => json({ status: 'not_configured' })));
    const second = renderApp('#/system');
    expect(await screen.findByText(/No local model is configured/)).toBeInTheDocument();
    second.unmount();
    stubHub(hub(() => json({ detail: 'Companion core unavailable' }, 502)));
    renderApp('#/system');
    expect(await screen.findByText(/Local model stats unavailable — Companion core unavailable/)).toBeInTheDocument();
  });

  it('rejects a malformed response instead of rendering it', () => {
    expect(() => parseLocalStats({ status: 'ok', model: { id: 3 } })).toThrow();
    expect(() => parseLocalStats({ status: 'ok', model: null, metrics: { requests_running: 'x' } })).toThrow();
    expect(() => parseLocalStats({ status: 'weird' })).toThrow();
  });
});
