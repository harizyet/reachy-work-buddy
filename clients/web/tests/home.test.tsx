import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mergeSection, parseHome, type HomeSnapshot, type Ref } from '../src/api/home';
import { weatherLines } from '../src/features/home/HomePage';
import { hrefFor } from '../src/features/home/links';
import { json, renderApp, SAMPLE_HOME, SAMPLE_STATUS, stubHub } from './helpers';

afterEach(() => vi.unstubAllGlobals());

const at = (h: number, m = 0) => new Date(2030, 0, 2, h, m).toISOString();
const ref = (screenName: Ref['screen'], id?: string): Ref => ({ screen: screenName, ...(id ? { id } : {}) });

const FULL = {
  ...SAMPLE_HOME,
  sources: { schedule: 'ok', tasks: 'ok', reminders: 'ok', reviews: 'ok', weather: 'ok' },
  schedule: {
    status: 'ok', feed_configured: true, feed: { configured: true, freshness: 'fresh' }, on_leave: true,
    all_day: [{ id: 'l', event_key: 'l', title: 'Annual leave', start: at(0), end: at(23, 59), all_day: true, classification: 'leave_or_ooo', location: null, status: 'confirmed', response: null, redacted: false, ref: ref('calendar', 'l') }],
    events: [
      { id: 'a', event_key: 'a', title: 'Standup', start: at(9), end: at(9, 30), all_day: false, classification: 'meeting', location: 'Room 4', status: 'confirmed', response: null, redacted: false, ref: ref('calendar', 'a') },
      { id: 'b', event_key: 'b', title: 'Busy', start: at(11), end: at(12), all_day: false, classification: 'busy_private', location: null, status: 'confirmed', response: null, redacted: true, ref: ref('calendar', 'b') },
    ],
    next_event: { id: 'a', event_key: 'a', title: 'Standup', start: at(9), end: at(9, 30), all_day: false, classification: 'meeting', location: 'Room 4', status: 'confirmed', response: null, redacted: false, ref: ref('calendar', 'a') },
  },
  tasks: {
    status: 'ok', total: 3, shown: 2, has_due_dates: false, from_meetings: 1, from_notes: 0,
    items: [
      { id: 't1', text: 'Contact the vendor', origin: { kind: 'meeting', meeting_id: 'm1', meeting_title: 'Cluster migration' }, ref: ref('tasks', 't1') },
      { id: 't2', text: 'Write the report', origin: null, ref: ref('tasks', 't2') },
    ],
  },
  reminders: {
    status: 'ok', upcoming_days: 7, counts: { overdue: 1, today: 1, upcoming: 1 },
    overdue: [{ id: 'r1', text: 'Pay rent', due_at: at(8), ref: ref('reminders', 'r1') }], today: [{ id: 'r2', text: 'Call the bank', due_at: at(17), ref: ref('reminders', 'r2') }],
    upcoming: [{ id: 'r3', text: 'Renew passport', due_at: at(10), ref: ref('reminders', 'r3') }],
  },
  reviews: {
    status: 'ok', total: 2,
    note_proposals: { status: 'ok', count: 1, items: [{ id: 'p1', kind: 'task', text: 'Renew the certificate', note_title: 'Weekly', ref: ref('notes', 'n1') }] },
    meeting_actions: { status: 'ok', count: 1, items: [{ id: 'i1', text: 'Update the schedule', assignee: 'Hariz', stated_time: 'tomorrow', meeting_title: 'Cluster migration', ref: ref('meetings', 'm1') }] },
  },
  weather: {
    status: 'ok', location: 'Singapore', observed_at: at(14), fetched_at: at(14), age_seconds: 0, attribution: { name: 'Open-Meteo.com', url: 'https://open-meteo.com/', license: 'CC BY 4.0' },
    units: { temperature: '°C', precipitation: 'mm', wind: 'km/h', humidity: '%', probability: '%' },
    current: { temperature: 30.4, feels_like: 36, humidity: 78, wind_speed: 9, precipitation: 0.4, summary: 'Light rain', raining: true },
    today: { high: 32.1, low: 26, precipitation_total: 7.5, precipitation_probability: 85, summary: 'Rain showers', sunrise: null, sunset: null },
  },
  quick_actions: [{ id: 'review_notes', label: 'Review 1 note suggestion', ref: ref('notes') }, { id: 'add_task', label: 'Add a task', ref: ref('tasks') }],
};

const signedIn = (home: unknown, extra: Record<string, () => Response> = {}) => ({
  '/auth/me': () => json({ username: 'owner' }), '/status': () => json(SAMPLE_STATUS), '/home': () => json(home), ...extra,
});

describe('Home', () => {
  it('is the landing page and fills every card from the snapshot', async () => {
    stubHub(signedIn(FULL));
    renderApp('#/');
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument();
    const schedule = within(await screen.findByRole('region', { name: "Today's schedule" }));
    expect(schedule.getByText('Annual leave')).toBeInTheDocument();
    expect(schedule.getByText('You are on leave today.')).toBeInTheDocument();
    expect(schedule.getAllByText('Standup').length).toBeGreaterThan(0);
    expect(schedule.getByText(/Room 4/)).toBeInTheDocument();
    expect(schedule.getByText('Busy')).toBeInTheDocument(); // busy-only: the placeholder, no invented detail
    const tasks = within(screen.getByRole('region', { name: 'Open tasks' }));
    expect(tasks.getByText(/3 open tasks · 1 from meetings · tasks have no due dates/)).toBeInTheDocument();
    expect(tasks.getByText('From meeting: Cluster migration')).toBeInTheDocument();
    expect(tasks.getByText('and 1 more')).toBeInTheDocument();
    const reminders = within(screen.getByRole('region', { name: 'Reminders' }));
    expect(reminders.getByText('OVERDUE')).toBeInTheDocument();
    for (const t of ['Pay rent', 'Call the bank', 'Renew passport']) expect(reminders.getByText(t)).toBeInTheDocument();
    const weather = within(screen.getByRole('region', { name: 'Weather' }));
    expect(weather.getByText(/Light rain · 30°C \(feels like 36°C\)/)).toBeInTheDocument();
    expect(weather.getByText(/Rain today: 7\.5 mm · up to 85% chance/)).toBeInTheDocument();
    expect(weather.getByRole('link', { name: 'Weather data by Open-Meteo.com' })).toHaveAttribute('href', 'https://open-meteo.com/');
    expect(screen.getByRole('link', { name: 'Review 1 note suggestion' })).toHaveAttribute('href', '#/notes');
  });

  it('shows suggestions as suggestions, never as tasks, and says so', async () => {
    stubHub(signedIn(FULL));
    renderApp('#/');
    const reviews = within(await screen.findByRole('region', { name: 'Waiting for your review' }));
    expect(reviews.getByText(/Nothing here is a task, reminder or note until you accept it/)).toBeInTheDocument();
    expect(reviews.getByText('Renew the certificate')).toBeInTheDocument();
    expect(reviews.getByText('Update the schedule')).toBeInTheDocument();
    const tasks = within(screen.getByRole('region', { name: 'Open tasks' }));
    expect(tasks.queryByText('Renew the certificate')).not.toBeInTheDocument();
    expect(tasks.queryByText('Update the schedule')).not.toBeInTheDocument();
  });

  it('opens each record in its existing screen', async () => {
    stubHub(signedIn(FULL));
    renderApp('#/');
    await screen.findByText('Contact the vendor');
    expect(screen.getAllByRole('link', { name: /Standup/ })[0]).toHaveAttribute('href', '#/calendar');
    expect(screen.getByRole('link', { name: 'Contact the vendor' })).toHaveAttribute('href', '#/todo');
    expect(screen.getByRole('link', { name: 'Pay rent' })).toHaveAttribute('href', '#/reminders');
    expect(screen.getByRole('link', { name: 'Renew the certificate' })).toHaveAttribute('href', '#/notes');
    expect(screen.getByRole('link', { name: 'Update the schedule' })).toHaveAttribute('href', '#/meetings/m1');
    expect(hrefFor(ref('talk'))).toBe('#/chat');
    expect(hrefFor(undefined)).toBe('#/');
    expect(hrefFor(ref('meetings', 'a/b'))).toBe('#/meetings/a%2Fb');
  });

  it('says what is true when everything is empty or off', async () => {
    stubHub(signedIn(SAMPLE_HOME));
    renderApp('#/');
    expect(await screen.findByText(/No calendar is connected/)).toBeInTheDocument();
    expect(screen.getByText('No open tasks.')).toBeInTheDocument();
    expect(screen.getByText(/No reminders due today or in the next 7 days/)).toBeInTheDocument();
    expect(screen.getByText('Note and meeting processing are turned off.')).toBeInTheDocument();
    expect(screen.getByText(/Set your location under/)).toBeInTheDocument();
  });

  it('a failed source marks only its own card; the others still show', async () => {
    const partial = { ...FULL, partial: true, sources: { ...FULL.sources, reminders: 'unavailable', weather: 'unavailable' }, reminders: { status: 'unavailable', error: 'section_failed' }, weather: { status: 'unavailable', error: 'timeout' } };
    stubHub(signedIn(partial));
    renderApp('#/');
    expect(await screen.findByText(/Some sources could not be read/)).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Reminders' })).getByText(/could not be read just now/)).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Weather' })).getByText(/could not be read just now/)).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Open tasks' })).getByText('Write the report')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: "Today's schedule" })).getByText('Standup', { selector: 'span' })).toBeInTheDocument();
  });

  it('marks a stale calendar and stale weather instead of presenting them as current', async () => {
    const stale = { ...FULL, schedule: { ...FULL.schedule, status: 'stale', feed: { configured: true, freshness: 'stale' } }, weather: { ...FULL.weather, status: 'stale', age_seconds: 7200 } };
    stubHub(signedIn(stale));
    renderApp('#/');
    expect(await screen.findByText(/The calendar may be out of date/)).toBeInTheDocument();
    expect(screen.getByText(/Out of date: last updated 120 minutes ago/)).toBeInTheDocument();
  });

  it('shows nothing, not even counts, for a restricted context', async () => {
    const locked = { ...SAMPLE_HOME, restricted: true, sources: { schedule: 'restricted', tasks: 'restricted', reminders: 'restricted', reviews: 'restricted', weather: 'restricted' },
      schedule: { status: 'restricted' }, tasks: { status: 'restricted' }, reminders: { status: 'restricted' }, reviews: { status: 'restricted' }, weather: { status: 'restricted' } };
    stubHub(signedIn(locked));
    renderApp('#/');
    expect(await screen.findAllByText('Not shown in this context.')).toHaveLength(5);
    expect(screen.getByRole('button', { name: 'Brief me on today' })).toBeDisabled();
    expect(document.body.textContent).not.toMatch(/\b\d+ open task/);
  });

  it('refreshes one section without reloading the page or touching the others', async () => {
    let tasksCalls = 0;
    // A stub that tells a full load from a one-section refresh by its query string.
    const seen: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://hub.test');
      if (url.pathname === '/auth/me') return json({ username: 'owner' });
      if (url.pathname === '/status') return json(SAMPLE_STATUS);
      if (url.pathname === '/home') {
        seen.push(url.search);
        if (url.search === '?sections=tasks') {
          tasksCalls += 1;
          return json({ ...FULL, schedule: undefined, reminders: undefined, reviews: undefined, weather: undefined, sources: { tasks: 'ok' }, tasks: { ...FULL.tasks, items: [{ id: 't9', text: 'A brand new task', origin: null, ref: ref('tasks', 't9') }], total: 1, shown: 1, from_meetings: 0 } });
        }
        return json(FULL);
      }
      throw new Error(`unexpected ${url.pathname}`);
    }));
    renderApp('#/');
    await screen.findByText('Contact the vendor');
    await userEvent.setup().click(screen.getByRole('button', { name: 'Refresh open tasks' }));
    expect(await screen.findByText('A brand new task')).toBeInTheDocument();
    expect(tasksCalls).toBe(1);
    expect(seen).toEqual(['', '?sections=tasks']); // one full load, one single-section refresh
    expect(within(screen.getByRole('region', { name: 'Reminders' })).getByText('Pay rent')).toBeInTheDocument(); // untouched
    expect(within(screen.getByRole('region', { name: "Today's schedule" })).getByText('Annual leave')).toBeInTheDocument();
  });

  it('"Brief me on today" shows the wording over the lines, labelled by what they are', async () => {
    stubHub(signedIn(FULL, {
      '/home/brief': () => json({
        generated_at: at(14), mode: 'generated', text: '- x', narrative: 'You have Standup at 9:00.', model: 'qwen-7b', fallback: null, partial: false, restricted: false,
        lines: [
          { category: 'calendar', status: 'confirmed', text: '09:00-09:30: Standup.', ref: ref('calendar', 'a'), urgency: 'normal' },
          { category: 'suggestion', status: 'pending_review', text: '1 note suggestion awaiting your review. They are not tasks or reminders until you accept them.', ref: ref('notes'), urgency: 'low' },
        ],
      }),
    }));
    renderApp('#/');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Brief me on today' }));
    const panel = within(await screen.findByRole('region', { name: "Today's briefing" }));
    expect(panel.getByText('You have Standup at 9:00.')).toBeInTheDocument();
    expect(panel.getByText(/Reworded by the local model \(qwen-7b\) from the lines below/)).toBeInTheDocument();
    expect(panel.getByText('Confirmed')).toBeInTheDocument();
    expect(panel.getByText('Suggestion')).toBeInTheDocument();
    expect(panel.getByRole('link', { name: '09:00-09:30: Standup.' })).toHaveAttribute('href', '#/calendar');
    await user.click(panel.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('region', { name: "Today's briefing" })).not.toBeInTheDocument();
  });

  it('falls back to the plain briefing when no wording was produced', async () => {
    const calls = stubHub(signedIn(FULL, {
      '/home/brief': () => json({ generated_at: at(14), mode: 'deterministic', text: '- a', narrative: null, model: null, fallback: 'unverified_wording', partial: true, restricted: false,
        lines: [{ category: 'calendar', status: 'confirmed', text: '09:00-09:30: Standup.', ref: null, urgency: 'normal' }] }),
    }));
    renderApp('#/');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Brief me on today' }));
    const panel = within(await screen.findByRole('region', { name: "Today's briefing" }));
    expect(panel.getByText(/A written summary was not available, so this is the plain briefing/)).toBeInTheDocument();
    expect(panel.getByText('09:00-09:30: Standup.')).toBeInTheDocument();
    expect(panel.getByText(/may be incomplete/)).toBeInTheDocument();
    const post = calls.find((c) => c.path === '/home/brief');
    expect(post?.method).toBe('POST');
    expect(post?.headers['X-Reachy-CSRF']).toBe('1');
    expect(post?.body).toEqual({ narrative: true });
  });

  it('renders hostile text literally and keeps nothing in browser storage', async () => {
    const hostile = { ...FULL, tasks: { ...FULL.tasks, items: [{ id: 'x', text: '<img src=x onerror=alert(1)>', origin: null, ref: ref('tasks', 'x') }] } };
    stubHub(signedIn(hostile));
    const { container } = renderApp('#/');
    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
    expect(JSON.stringify({ ...window.localStorage })).not.toMatch(/vendor|rent/);
  });

  it('keeps System reachable and the system page intact', async () => {
    stubHub(signedIn(FULL));
    renderApp('#/system');
    expect(await screen.findByRole('heading', { name: 'System status' })).toBeInTheDocument();
  });
});

describe('Home data helpers', () => {
  it('rejects a snapshot whose section has an unknown status', () => {
    expect(() => parseHome({ generated_at: 'x', sources: {}, tasks: { status: 'weird' } })).toThrow(/home\.tasks/);
    expect(() => parseHome(null)).toThrow();
    expect(parseHome(SAMPLE_HOME).date).toBe('2030-01-02');
  });

  it('merges one refreshed section and recomputes partial from the sources', () => {
    const old = { ...(FULL as unknown as HomeSnapshot), partial: true, sources: { ...FULL.sources, weather: 'unavailable' } } as HomeSnapshot;
    const fresh = { ...(FULL as unknown as HomeSnapshot), sources: { weather: 'ok' }, generated_at: 'later' } as HomeSnapshot;
    const merged = mergeSection(old, fresh, 'weather');
    expect(merged.partial).toBe(false);
    expect(merged.sources.weather).toBe('ok');
    expect(merged.tasks).toBe(old.tasks);
    expect(merged.generated_at).toBe('later');
  });

  it('formats weather from provider numbers only', () => {
    const w = (FULL as unknown as HomeSnapshot).weather!;
    expect(weatherLines(w)).toEqual(['Light rain · 30°C (feels like 36°C)', 'Today 26°C to 32°C · Rain showers', 'Rain today: 7.5 mm · up to 85% chance']);
    expect(weatherLines({ status: 'unavailable' })).toEqual([]);
  });
});
