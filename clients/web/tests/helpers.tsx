import { QueryClient } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { vi } from 'vitest';
import { Providers, makeQueryClient } from '../src/app/providers';
import { AppRouter } from '../src/app/router';
import samples from '../src/api/samples.json';

export const SAMPLE_STATUS = samples.status;

export interface Call {
  path: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

type Handler = (call: Call) => Response | Promise<Response>;

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

/** Stubs fetch with a path-keyed table; unknown paths fail the test loudly. */
export function stubHub(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), 'http://hub.test').pathname;
      const call: Call = {
        path,
        method: init?.method ?? 'GET',
        headers: (init?.headers ?? {}) as Record<string, string>,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      };
      calls.push(call);
      const handler = routes[path];
      if (!handler) throw new Error(`unexpected request ${call.method} ${path}`);
      return handler(call);
    }),
  );
  return calls;
}

export function testQueryClient(): QueryClient {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retryDelay: 0 } });
  return client;
}

export function renderApp(hash = '#/', client: QueryClient = testQueryClient()) {
  window.location.hash = hash;
  return { client, ...render(<Providers client={client}><AppRouter /></Providers>) };
}
