process.env.TZ = 'Asia/Singapore'; // the owner's zone for these tests; Date reads it lazily

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { FeedEvent } from '../src/api/calendarFeed';
import { dayMarkers, eventsOn, isCached, monthGrid, onDay, reminderText, sourceText, syncStateText, titleOf, upcomingMeetings, whenText } from '../src/features/calendar/calendarLogic';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

// ADR 0035 addendum: the Calendar page. Logic first (pure), then the page against a fake hub that follows the contract pinned by test_calendar_sync.py and test_calendar_feed_api.py.

const ev = (over: Partial<FeedEvent> = {}): FeedEvent => ({
  title: 'Design review', start: '2026-10-13T02:00:00Z', end: '2026-10-13T03:00:00Z', location: null, all_day: false, classification: 'meeting', classification_basis: 'explicit',
  classification_reasons: ['attendees'], status: 'confirmed', response: null, redacted: false, title_missing: false, source: 'ics', event_key: 'ics:a:0', series_key: 'ics:a', recurring: false,
  remind: true, remind_blocked: null, ...over,
});
const leave = ev({ title: 'Annual leave', all_day: true, classification: 'leave_or_ooo', start: '2026-10-18T16:00:00Z', end: '2026-10-21T16:00:00Z', remind: false, remind_blocked: 'all_day', event_key: 'ics:l:0' }); // 19 to 21 Oct SGT
const busy = ev({ title: 'Busy', redacted: true, classification: 'busy_private', remind: false, event_key: 'ics:b:0', start: '2026-10-13T05:00:00Z', end: '2026-10-13T06:00:00Z' });
const day = (d: number) => new Date(2026, 9, d);

describe('calendar logic', () => {
  it('lays a month out as six Monday-first weeks', () => {
    const grid = monthGrid(new Date(2026, 9, 1)); // 1 Oct 2026 is a Thursday
    expect(grid).toHaveLength(42);
    expect(grid[0]).toEqual(new Date(2026, 8, 28));
    expect(grid[41]).toEqual(new Date(2026, 10, 8));
    expect(grid.filter((d) => d.getMonth() === 9)).toHaveLength(31);
  });

  it('shows multi-day leave on every day it covers and not on its exclusive end', () => {
    for (const d of [19, 20, 21]) expect(onDay(leave, day(d))).toBe(true);
    expect(onDay(leave, day(18))).toBe(false);
    expect(onDay(leave, day(22))).toBe(false);
    const label = (d: Date) => d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
    expect(whenText(leave)).toBe(`All day, ${label(day(19))} to ${label(day(21))}`);
  });

  it('puts events in chronological order in the owner time zone and leaves out cancelled and declined ones', () => {
    const late = ev({ title: 'Late', start: '2026-10-13T08:00:00Z', end: '2026-10-13T09:00:00Z', event_key: 'ics:z' });
    const early = ev({ title: 'Early', start: '2026-10-12T23:30:00Z', end: '2026-10-13T00:00:00Z', event_key: 'ics:y' }); // 07:30 on the 13th in Singapore
    const cancelled = ev({ title: 'Gone', status: 'cancelled', event_key: 'ics:c' });
    const declined = ev({ title: 'No', response: 'declined', event_key: 'ics:d' });
    expect(eventsOn([late, cancelled, ev(), declined, early, leave], day(13)).map((e) => e.title)).toEqual(['Early', 'Design review', 'Late']);
    expect(whenText(ev(), day(13))).toBe('10:00–11:00');
    expect(whenText(early, day(13))).toBe('07:30–08:00');
  });

  it('shows a Busy entry as Busy with its interval and nothing else', () => {
    expect(titleOf(busy)).toBe('Busy');
    expect(whenText(busy, day(13))).toBe('13:00–14:00');
    expect(reminderText(busy)).toBe('No reminder: details hidden');
    expect(titleOf(ev({ title: '(untitled event)', title_missing: true }))).toBe('Untitled event');
  });

  it('marks days and says why a reminder is or is not set', () => {
    expect(dayMarkers([ev(), leave, busy], day(13))).toEqual(['meeting', 'other']);
    expect(dayMarkers([leave], day(20))).toEqual(['leave']);
    expect(dayMarkers([leave], day(22))).toEqual([]);
    expect(reminderText(ev())).toBe('Recording reminder on');
    expect(reminderText(leave)).toBe('No reminder: all-day');
    expect(reminderText(ev({ remind: false, remind_blocked: 'not_a_meeting:personal_appointment', classification: 'personal_appointment' }))).toBe('No reminder: personal appointment');
    expect(reminderText(ev({ remind: false, remind_blocked: 'on_leave' }))).toBe('No reminder: you are on leave');
  });

  it('lists only meetings that have not finished as upcoming, soonest first', () => {
    const now = new Date('2026-10-13T02:30:00Z');
    const later = ev({ title: 'Later', start: '2026-10-14T02:00:00Z', end: '2026-10-14T03:00:00Z', event_key: 'ics:q' });
    const past = ev({ title: 'Past', start: '2026-10-12T02:00:00Z', end: '2026-10-12T03:00:00Z', event_key: 'ics:p' });
    expect(upcomingMeetings([later, past, busy, leave, ev()], now).map((e) => e.title)).toEqual(['Design review', 'Later']); // the one running now counts
  });

  it('words the sync state, the source and the cached indication', () => {
    expect(syncStateText({ sync_state: 'error', freshness: 'fresh' })).toMatch(/failed/);
    expect(isCached({ sync_state: 'error', freshness: 'fresh' })).toBe(true);
    expect(isCached({ sync_state: 'ok', freshness: 'fresh' })).toBe(false);
    expect(sourceText({ configured: true, host: 'week.ics', source: 'upload' })).toBe('Uploaded file (week.ics)');
    expect(sourceText({ configured: true, host: 'calendar.example.com', source: 'url' })).toBe('Calendar link (calendar.example.com)');
    expect(sourceText({ configured: false, host: null, source: null })).toBe('None');
  });
});

const brief = (over: Record<string, unknown> = {}) => ({
  configured: true, host: 'calendar.example.com', source: 'url', freshness: 'fresh', sync_state: 'ok', last_success_at: '2026-10-13T01:00:00Z', last_attempt_at: '2026-10-13T01:05:00Z', age_seconds: 60,
  error: null, consecutive_failures: 0, event_count: 3, truncated: false, generation: 4, snapshot_revision: 'abc', ...over,
});

function setup(options: { feed?: Record<string, unknown>; events?: FeedEvent[] } = {}) {
  createFakeHub({ status: { ...SAMPLE_STATUS, default_user_id: 'owner-user', owner_bound: true } });
  const base = globalThis.fetch;
  const server = { feed: brief(options.feed), events: options.events ?? [], calls: [] as string[], generation: 4 };
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://hub.test');
    if (!url.pathname.startsWith('/calendar-feed')) return base(input, init);
    const call = `${init?.method ?? 'GET'} ${url.pathname}`;
    server.calls.push(call);
    if (call === 'GET /calendar-feed/schedule') return jsonResponse({ generation: server.generation, snapshot_revision: 'abc', generated_at: '2026-10-13T01:06:00Z', feed: { ...server.feed, generation: server.generation }, events: server.events });
    if (call === 'POST /calendar-feed/refresh') return jsonResponse({ ...server.feed, config: {}, overrides: {}, generation: server.generation });
    return jsonResponse({ detail: 'Not Found' }, 404);
  }));
  return server;
}

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('Calendar page', () => {
  it('says no calendar is set up and points to Settings', async () => {
    setup({ feed: brief({ configured: false, host: null, source: null, freshness: 'not_configured', sync_state: 'not_configured', last_success_at: null, event_count: 0 }) });
    renderApp('#/calendar');
    expect(await screen.findByText('No calendar set up', { selector: 'h2' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Settings > Accounts/ })).toHaveAttribute('href', '#/settings/accounts');
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeDisabled();
    expect(screen.getByText('No calendar is set up.')).toBeInTheDocument();
  });

  it('shows the selected day, its events in order with classification and reminder status, and an empty-day state', async () => {
    vi.setSystemTime(new Date('2026-10-13T01:00:00Z'));
    setup({ events: [busy, ev({ title: 'Dentist', classification: 'personal_appointment', remind: false, remind_blocked: 'not_a_meeting:personal_appointment', event_key: 'ics:d', start: '2026-10-13T08:00:00Z', end: '2026-10-13T09:00:00Z' }), ev(), leave] });
    renderApp('#/calendar');
    const user = userEvent.setup();
    const agenda = within(await screen.findByRole('region', { name: 'Agenda' }));
    await waitFor(() => expect(agenda.getAllByTestId('class-chip').map((c) => c.textContent)).toEqual(['Meeting', 'Busy', 'Appointment']));
    const rows = agenda.getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('10:00–11:00'); expect(rows[0]).toHaveTextContent('Recording reminder on');
    expect(rows[1]).toHaveTextContent('13:00–14:00'); expect(rows[1]).toHaveTextContent('Busy'); expect(rows[1]).toHaveTextContent('No reminder: details hidden');
    expect(rows[2]).toHaveTextContent('No reminder: personal appointment');
    await user.click(screen.getByRole('gridcell', { name: /Monday.*19/ }));
    const leaveDay = within(screen.getByRole('region', { name: 'Agenda' }));
    expect(leaveDay.getByText('Annual leave')).toBeInTheDocument();
    expect(leaveDay.getByTestId('class-chip')).toHaveTextContent('Leave');
    expect(leaveDay.getByText(/^All day, .*19.* to .*21/)).toBeInTheDocument();
    expect(leaveDay.getByText('No reminder: all-day')).toBeInTheDocument();
    await user.click(screen.getByRole('gridcell', { name: /Thursday.*22/ }));
    expect(screen.getByText('Nothing on this day.')).toBeInTheDocument();
  });

  it('lists upcoming meetings and shows the two clocks, the count, the source and the revision', async () => {
    vi.setSystemTime(new Date('2026-10-13T01:00:00Z'));
    setup({ events: [ev(), busy, leave], feed: brief({ event_count: 3 }) });
    renderApp('#/calendar');
    const upcoming = within(await screen.findByRole('heading', { name: 'Upcoming meetings' }).then((h) => h.closest('section')!));
    expect(upcoming.getAllByRole('listitem')).toHaveLength(1);
    expect(upcoming.getByText('Design review')).toBeInTheDocument();
    const status = within(await screen.findByLabelText('Sync details'));
    expect(status.getByText('Up to date')).toBeInTheDocument();
    expect(status.getByText('Calendar link (calendar.example.com)')).toBeInTheDocument();
    expect(status.getByText(/Last successful refresh of the source/)).toBeInTheDocument();
    expect(status.getByText(/This page last checked the server/)).toBeInTheDocument();
    expect(status.getByText('3')).toBeInTheDocument();
    expect(status.getByText('4')).toBeInTheDocument();
  });

  it('shows the last error and marks the copy as cached', async () => {
    setup({ feed: brief({ sync_state: 'error', error: 'timeout', consecutive_failures: 2 }), events: [ev()] });
    renderApp('#/calendar');
    const status = within(await screen.findByLabelText('Sync details'));
    expect(status.getByText(/Last refresh failed/)).toHaveTextContent('(cached)');
    expect(status.getByText('The calendar server took too long to answer.')).toBeInTheDocument();
  });

  it('refreshes on demand and shows the new revision straight away', async () => {
    vi.setSystemTime(new Date('2026-10-13T01:00:00Z'));
    const server = setup({ events: [ev()] });
    renderApp('#/calendar');
    const user = userEvent.setup();
    const agenda = await screen.findByRole('region', { name: 'Agenda' });
    await waitFor(() => expect(within(agenda).getAllByRole('listitem')).toHaveLength(1));
    server.events = [ev(), ev({ title: 'Added after refresh', event_key: 'ics:n', start: '2026-10-13T04:00:00Z', end: '2026-10-13T05:00:00Z' })];
    server.generation = 5;
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(within(screen.getByRole('region', { name: 'Agenda' })).getByText('Added after refresh')).toBeInTheDocument());
    expect(server.calls).toContain('POST /calendar-feed/refresh');
    expect(within(screen.getByLabelText('Sync details')).getByText('5')).toBeInTheDocument();
  });
});
