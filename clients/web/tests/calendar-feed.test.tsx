import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

// ADR 0035 on Settings > Accounts: the calendar feed card. The fake server follows the contract pinned by services/companion-core/tests/test_calendar_feed_api.py and
// services/reachy-hub/tests/test_calendar_feed_hub.py. The URL is write-only: these tests check it is sent once and that nothing the page shows can contain it.

const FEED_URL = 'https://calendar.example.com/private/abcdef-secret-token/basic.ics';
const config = (over: Record<string, unknown> = {}) => ({ refresh_minutes: 15, lead_minutes: 5, horizon_days: 60, device_horizon_hours: 72, timezone: null, rules: { owner_emails: [], remind_keyword_meetings: true, leave_suppresses_meetings: false }, ...over });
const status = (over: Record<string, unknown> = {}) => ({
  configured: false, host: null, freshness: 'not_configured', last_success_at: null, last_attempt_at: null, age_seconds: null, error: null, consecutive_failures: 0, event_count: 0, truncated: false,
  config: config(), overrides: {}, ...over,
});
const ev = (over: Record<string, unknown> = {}) => ({
  title: 'Design review', start: '2030-01-03T06:00:00Z', end: '2030-01-03T07:00:00Z', location: null, all_day: false, classification: 'meeting', classification_basis: 'explicit', classification_reasons: ['attendees'],
  status: 'confirmed', response: null, redacted: false, title_missing: false, source: 'ics', event_key: 'ics:a:0', series_key: 'ics:a', recurring: false, remind: true, remind_blocked: null, ...over,
});

function setup(options: { feed?: Record<string, unknown>; events?: Record<string, unknown>[]; saveError?: { code: number; detail: string }; uploadError?: string } = {}) {
  const uploads: { type: string; name: string; body: unknown }[] = [];
  createFakeHub({ status: { ...SAMPLE_STATUS, default_user_id: 'owner-user', owner_bound: true } });
  const base = globalThis.fetch;
  const server = { feed: status(options.feed), events: options.events ?? [], calls: [] as { call: string; body: any }[] };
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://hub.test');
    if (!url.pathname.startsWith('/calendar-feed')) return base(input, init);
    const method = init?.method ?? 'GET';
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined; // an upload sends the file itself
    const call = `${method} ${url.pathname}`;
    server.calls.push({ call, body });
    if (call === 'GET /calendar-feed') return jsonResponse(server.feed);
    if (call === 'PUT /calendar-feed') {
      if (body.url && options.saveError) return jsonResponse({ detail: options.saveError.detail }, options.saveError.code);
      if (body.url) server.feed = status({ configured: true, host: new URL(body.url).hostname, freshness: 'fresh', last_success_at: '2030-01-02T07:00:00Z', age_seconds: 0, event_count: server.events.length, config: server.feed.config, overrides: server.feed.overrides });
      if (body.config) server.feed = { ...server.feed, config: body.config } as any;
      return jsonResponse(server.feed);
    }
    if (call === 'PUT /calendar-feed/upload') {
      uploads.push({ type: String((init?.headers as Record<string, string>)['Content-Type']), name: decodeURIComponent(String((init?.headers as Record<string, string>)['X-Filename'])), body: init?.body });
      if (options.uploadError) return jsonResponse({ detail: options.uploadError }, 400);
      server.feed = status({ configured: true, host: uploads.at(-1)!.name, source: 'upload', freshness: 'fresh', sync_state: 'ok', last_success_at: '2030-01-02T07:00:00Z', age_seconds: 0, event_count: 5, generation: 7, config: server.feed.config, overrides: {} });
      return jsonResponse(server.feed);
    }
    if (call === 'POST /calendar-feed/refresh') return jsonResponse(server.feed);
    if (call === 'DELETE /calendar-feed') { server.feed = status({ config: server.feed.config }); return jsonResponse(server.feed); }
    if (call === 'GET /calendar-feed/events') return jsonResponse(server.events);
    if (call === 'PUT /calendar-feed/overrides') {
      server.feed = { ...server.feed, overrides: { ...(server.feed.overrides as object), [body.key]: body.classification } } as any;
      server.events = server.events.map((e) => (e.event_key === body.key ? { ...e, classification: body.classification, classification_basis: 'owner', remind: body.classification === 'meeting' } : e));
      return jsonResponse(server.feed);
    }
    if (call === 'DELETE /calendar-feed/overrides') return jsonResponse(server.feed);
    return jsonResponse({ detail: 'Not Found' }, 404);
  }));
  return Object.assign(server, { uploads });
}

afterEach(() => vi.unstubAllGlobals());

const card = async () => within(await screen.findByRole('region', { name: 'Calendar feed (read-only)' }));

describe('Calendar feed card', () => {
  it('starts empty, sends the link once through a hidden field and never shows it again', async () => {
    const server = setup();
    renderApp('#/settings/accounts');
    const user = userEvent.setup();
    const c = await card();
    await waitFor(() => expect(c.getByLabelText('Calendar feed status')).toHaveTextContent('No feed set up.'));
    const field = c.getByLabelText(/Calendar link/);
    expect(field).toHaveAttribute('type', 'password');
    await user.type(field, FEED_URL);
    await user.click(c.getByRole('button', { name: 'Save link' }));
    await waitFor(() => expect(c.getByLabelText('Calendar feed status')).toHaveTextContent('Feed from calendar.example.com. Up to date'));
    expect(server.calls.find((x) => x.call === 'PUT /calendar-feed' && x.body.url)?.body).toEqual({ url: FEED_URL });
    expect(field).toHaveValue('');
    expect(document.body.textContent).not.toContain('secret-token');
    expect(document.body.innerHTML).not.toContain('secret-token');
  });

  it('says what is wrong in words and does not echo what was sent', async () => {
    setup({ saveError: { code: 400, detail: 'unsafe_address' } });
    renderApp('#/settings/accounts');
    const user = userEvent.setup();
    const c = await card();
    await user.type(await c.findByLabelText(/Calendar link/), FEED_URL);
    await user.click(c.getByRole('button', { name: 'Save link' }));
    expect(await screen.findByText(/private or internal network/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('secret-token');
  });

  it('shows freshness, a failed refresh and a stale copy honestly', async () => {
    setup({ feed: { configured: true, host: 'calendar.example.com', freshness: 'stale', last_success_at: '2030-01-02T01:00:00Z', age_seconds: 99999, error: 'http_503', consecutive_failures: 3, event_count: 12 } });
    renderApp('#/settings/accounts');
    const c = await card();
    const line = await c.findByLabelText('Calendar feed status');
    expect(line).toHaveTextContent('Out of date: the last good copy is being used');
    expect(line).toHaveTextContent('The calendar server answered 503.');
    expect(line).toHaveTextContent('12 events');
  });

  it('saves the lead time, the interval, the owner addresses and the two switches', async () => {
    const server = setup({ feed: { configured: true, host: 'calendar.example.com', freshness: 'fresh', last_success_at: '2030-01-02T07:00:00Z', age_seconds: 0 } });
    renderApp('#/settings/accounts');
    const user = userEvent.setup();
    const c = await card();
    const form = within(await c.findByRole('form', { name: 'Calendar feed settings' }));
    const lead = form.getByLabelText(/minutes before a meeting/);
    await user.clear(lead); await user.type(lead, '10');
    await user.type(form.getByLabelText(/Your email addresses/), 'me@example.com, me@work.example');
    await user.click(form.getByLabelText(/on a day I am on leave/));
    await user.click(form.getByRole('button', { name: 'Save settings' }));
    await waitFor(() => expect(server.calls.some((x) => x.call === 'PUT /calendar-feed' && x.body.config)).toBe(true));
    const sent = server.calls.find((x) => x.body?.config)!.body.config;
    expect(sent.lead_minutes).toBe(10);
    expect(sent.rules.owner_emails).toEqual(['me@example.com', 'me@work.example']);
    expect(sent.rules.leave_suppresses_meetings).toBe(true);
    expect(sent.rules.remind_keyword_meetings).toBe(true);
  });

  it('lists the events with the same classification the phone shows and lets the owner override one', async () => {
    const server = setup({
      feed: { configured: true, host: 'calendar.example.com', freshness: 'fresh', last_success_at: '2030-01-02T07:00:00Z', age_seconds: 0, event_count: 5 },
      events: [
        ev(),
        ev({ title: 'Dentist appointment', classification: 'personal_appointment', classification_basis: 'rule', remind: false, remind_blocked: 'not_a_meeting:personal_appointment', event_key: 'ics:b:0' }),
        ev({ title: 'Annual leave', classification: 'leave_or_ooo', classification_basis: 'rule', all_day: true, start: '2030-01-07T00:00:00Z', end: '2030-01-10T00:00:00Z', remind: false, remind_blocked: 'all_day', event_key: 'ics:c:0' }),
        ev({ title: 'Busy', classification: 'busy_private', redacted: true, remind: false, event_key: 'ics:d:0' }),
        ev({ title: '(untitled event)', title_missing: true, event_key: 'ics:e:0' }),
      ],
    });
    renderApp('#/settings/accounts');
    const user = userEvent.setup();
    const c = await card();
    const list = within(await c.findByRole('region', { name: 'Next 7 days' }));
    await waitFor(() => expect(list.getAllByTestId('class-chip').map((x) => x.textContent)).toEqual(['Meeting', 'Appointment', 'Leave', 'Busy', 'Meeting']));
    expect(list.getByText('Untitled event')).toBeInTheDocument();
    expect(list.queryByText('(untitled event)')).not.toBeInTheDocument();
    const items = list.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('reminder on');
    expect(items[2]).toHaveTextContent(/to .*Wed|to .*Thu|to .*Tue/);  // a three-day leave shows its span; the exclusive end day is not part of it
    await user.selectOptions(list.getByLabelText('Classification of Dentist appointment'), 'Meeting');
    await waitFor(() => expect(server.calls.find((x) => x.call === 'PUT /calendar-feed/overrides')?.body).toEqual({ key: 'ics:b:0', classification: 'meeting' }));
    await waitFor(() => expect(within(screen.getByRole('region', { name: 'Next 7 days' })).getAllByRole('listitem')[1]).toHaveTextContent('set by you'));
  });

  it('removes the feed', async () => {
    const server = setup({ feed: { configured: true, host: 'calendar.example.com', freshness: 'fresh', last_success_at: '2030-01-02T07:00:00Z', age_seconds: 0 } });
    renderApp('#/settings/accounts');
    const user = userEvent.setup();
    const c = await card();
    await user.click(await c.findByRole('button', { name: 'Remove feed' }));
    await waitFor(() => expect(c.getByLabelText('Calendar feed status')).toHaveTextContent('No feed set up.'));
    expect(server.calls.map((x) => x.call)).toContain('DELETE /calendar-feed');
  });

  it('uploads an ICS file as the new source and shows what was loaded; a file that cannot be read is refused in words', async () => {
    const server = setup({ feed: { configured: true, host: 'calendar.example.com', freshness: 'fresh', last_success_at: '2030-01-02T07:00:00Z', age_seconds: 0 } });
    renderApp('#/settings/accounts');
    const user = userEvent.setup();
    const c = await card();
    const file = new File(['BEGIN:VCALENDAR\nEND:VCALENDAR\n'], 'my week.ics', { type: 'text/calendar' });
    await user.upload(await c.findByLabelText('Upload an ICS file'), file);
    await waitFor(() => expect(c.getByLabelText('Calendar feed status')).toHaveTextContent('Uploaded file my week.ics. Up to date'));
    expect(server.uploads[0]).toMatchObject({ type: 'text/calendar', name: 'my week.ics' });
    expect(server.uploads[0]!.body).toBe(file);
    expect(screen.getByText('Calendar file loaded: 5 events.')).toBeInTheDocument();
  });

  it('refuses a bad file and keeps the status as it was', async () => {
    setup({ feed: { configured: true, host: 'calendar.example.com', freshness: 'fresh', last_success_at: '2030-01-02T07:00:00Z', age_seconds: 0 }, uploadError: 'not_calendar' });
    renderApp('#/settings/accounts');
    const user = userEvent.setup();
    const c = await card();
    await user.upload(await c.findByLabelText('Upload an ICS file'), new File(['<html>'], 'x.ics'));
    expect(await screen.findByText(/did not return a calendar/)).toBeInTheDocument();
    expect(c.getByLabelText('Calendar feed status')).toHaveTextContent('Feed from calendar.example.com');
  });
});
