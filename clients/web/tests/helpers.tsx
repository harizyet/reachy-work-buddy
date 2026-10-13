import { screen, within } from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';
import { QueryClient } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { vi } from 'vitest';
import { Providers, makeQueryClient } from '../src/app/providers';
import { AppRouter } from '../src/app/router';
import samples from '../src/api/samples.json';

export const SAMPLE_STATUS = samples.status;

/** A minimal valid Home snapshot: every source empty, nothing private. */
export const SAMPLE_HOME = {
  generated_at: '2030-01-02T08:00:00+00:00', timezone: 'UTC', date: '2030-01-02', partial: false, restricted: false, quick_actions: [],
  sources: { schedule: 'empty', tasks: 'empty', reminders: 'empty', reviews: 'off', weather: 'not_configured' },
  schedule: { status: 'empty', events: [], all_day: [], next_event: null, feed_configured: false },
  tasks: { status: 'empty', total: 0, shown: 0, items: [] },
  reminders: { status: 'empty', upcoming_days: 7, counts: { overdue: 0, today: 0, upcoming: 0 }, overdue: [], today: [], upcoming: [] },
  reviews: { status: 'off', total: 0 },
  weather: { status: 'not_configured', detail: 'no_location' },
};

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

const NAV_GROUP: Record<string, string> = {
  Meetings: 'Library', Notes: 'Library', Documents: 'Library',
  'To Do': 'Planner', Reminders: 'Planner', Alarms: 'Planner', Calendar: 'Planner',
  Memory: 'Assistant', Activity: 'Assistant', Brain: 'Assistant', 'Coding agents': 'Assistant', System: 'Assistant',
};

/** Opens the category menu holding a page link (top-level links need no menu) and returns the link. */
export async function navLink(user: UserEvent, name: string) {
  const group = NAV_GROUP[name];
  if (group) {
    const nav = within(await screen.findByRole('navigation', { name: 'Main' }));
    const button = nav.getByRole('button', { name: new RegExp(`^${group}`) });
    if (button.getAttribute('aria-expanded') !== 'true') await user.click(button);
  }
  return screen.findByRole('link', { name });
}
