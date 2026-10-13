import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { getSchedule, feedProblem, refreshFeed } from '../../api/calendarFeed';
import { StaleSessionError } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Spinner } from '../../components/ui/Spinner';
import {
  addDays,
  ago,
  classLabel,
  dayMarkers,
  eventsOn,
  isCached,
  monthGrid,
  reminderText,
  sameDay,
  sourceText,
  startOfDay,
  syncStateText,
  titleOf,
  upcomingMeetings,
  whenText,
} from './calendarLogic';

const KEY = ['calendar-schedule'];
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// The Calendar page (ADR 0035). It reads ONE revision through /calendar-feed/schedule: the events and the feed's status come from the same state, and the page re-reads when the
// revision changes (every 20 seconds and whenever the tab comes back), so an upload, a new link or a refresh shows up here without a reload.
export function CalendarPage() {
  const client = useQueryClient();
  const today = startOfDay(new Date());
  const [month, setMonth] = useState(new Date(today.getFullYear(), today.getMonth(), 1));
  const [selected, setSelected] = useState(today);
  const grid = useMemo(() => monthGrid(month), [month]);
  const from = grid[0] as Date;
  const until = addDays(grid[41] as Date, 1);
  const horizon = addDays(today, 14);
  const schedule = useQuery({
    queryKey: [...KEY, from.toISOString(), until.toISOString()],
    queryFn: ({ signal }) => getSchedule(from < today ? from : today, until > horizon ? until : horizon, signal),
    refetchInterval: 20_000,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const [message, setMessage] = useState('');
  const refresh = useMutation({
    mutationFn: refreshFeed,
    onSuccess: (s) => {
      setMessage(s.error ? feedProblem(s.error) : 'Refreshed.');
      void client.invalidateQueries({ queryKey: KEY });
    },
    onError: (e) => !(e instanceof StaleSessionError) && setMessage(e instanceof Error ? feedProblem(e.message) : 'Something went wrong'),
  });
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);

  const data = schedule.data;
  const feed = data?.feed;
  const events = data?.events ?? [];
  const day = eventsOn(events, selected);
  const upcoming = upcomingMeetings(events, now);
  const title = month.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Calendar</h1>
      {schedule.isPending && <Spinner label="Loading the calendar" />}
      {schedule.error && !(schedule.error instanceof StaleSessionError) && <p role="alert" className="text-sm">{schedule.error.message}</p>}
      {feed && !feed.configured && (
        <Card title="No calendar set up">
          <p className="text-sm">Reachy has no calendar to show yet. Add the link to your calendar, or upload an .ics file, under <a className="underline" href="#/settings/accounts">Settings &gt; Accounts</a>.</p>
        </Card>
      )}
      {data && (
        <>
          <Card title="Sync status" eyebrow="CALENDAR">
            <dl className="grid gap-x-6 gap-y-1 text-sm md:grid-cols-2" aria-label="Sync details">
              <div><dt className="inline text-[var(--muted)]">State: </dt><dd className="inline">{syncStateText(data.feed)}{isCached(data.feed) && ' (cached)'}</dd></div>
              <div><dt className="inline text-[var(--muted)]">Source: </dt><dd className="inline">{sourceText(data.feed)}</dd></div>
              <div><dt className="inline text-[var(--muted)]">Last successful refresh of the source: </dt><dd className="inline">{data.feed.last_success_at ? `${new Date(data.feed.last_success_at).toLocaleString()} (${ago(data.feed.last_success_at, now)})` : 'never'}</dd></div>
              <div><dt className="inline text-[var(--muted)]">This page last checked the server: </dt><dd className="inline">{new Date(schedule.dataUpdatedAt).toLocaleTimeString()}</dd></div>
              <div><dt className="inline text-[var(--muted)]">Events: </dt><dd className="inline">{data.feed.event_count}</dd></div>
              <div><dt className="inline text-[var(--muted)]">Revision: </dt><dd className="inline">{data.generation}</dd></div>
              {data.feed.error && <div className="md:col-span-2"><dt className="inline text-[var(--muted)]">Last error: </dt><dd className="inline">{feedProblem(data.feed.error)}</dd></div>}
            </dl>
            <div className="mt-2 flex items-center gap-3">
              <Button disabled={refresh.isPending || !data.feed.configured} onClick={() => refresh.mutate()}>{refresh.isPending ? 'Refreshing…' : 'Refresh'}</Button>
              <p role="status" className="text-sm">{message}</p>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Card title={title}>
              <div className="mb-2 flex items-center gap-2">
                <Button variant="secondary" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>‹</Button>
                <Button variant="secondary" onClick={() => { setMonth(new Date(today.getFullYear(), today.getMonth(), 1)); setSelected(today); }}>Today</Button>
                <Button variant="secondary" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>›</Button>
              </div>
              <div role="grid" aria-label={`Month of ${title}`} className="grid grid-cols-7 gap-1 text-center text-sm">
                {WEEKDAYS.map((w) => <div key={w} role="columnheader" className="text-xs text-[var(--muted)]">{w}</div>)}
                {grid.map((d) => {
                  const marks = dayMarkers(events, d);
                  const isSel = sameDay(d, selected);
                  return (
                    <button
                      key={d.toISOString()}
                      type="button"
                      role="gridcell"
                      aria-selected={isSel}
                      aria-label={`${d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}${marks.length ? `, ${marks.join(', ')}` : ''}`}
                      onClick={() => setSelected(d)}
                      className={`rounded border p-1 ${isSel ? 'border-[var(--accent)] bg-[var(--accent)] text-white' : 'border-[var(--border)]'} ${d.getMonth() !== month.getMonth() ? 'opacity-50' : ''} ${sameDay(d, today) ? 'font-bold' : ''}`}
                    >
                      <span className="block">{d.getDate()}</span>
                      <span className="flex h-2 justify-center gap-0.5" aria-hidden="true">
                        {marks.includes('meeting') && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
                        {marks.includes('leave') && <span className="h-1.5 w-1.5 rounded-sm bg-current opacity-60" />}
                        {marks.includes('other') && <span className="h-1.5 w-1.5 rounded-full border border-current" />}
                      </span>
                    </button>
                  );
                })}
              </div>
              <p className="mt-1 text-xs text-[var(--muted)]">● meeting · ■ leave · ○ other events</p>
            </Card>

            <Card title="Upcoming meetings">
              {upcoming.length === 0 ? <p className="text-sm">{data.feed.configured ? 'No upcoming meetings.' : 'Nothing to show until a calendar is set up.'}</p> : (
                <ul className="divide-y divide-[var(--border)]">
                  {upcoming.map((e) => (
                    <li key={e.event_key ?? e.start + e.title} className="py-2 text-sm">
                      <span className="font-medium">{titleOf(e)}</span>
                      <span className="block text-[var(--muted)]">{whenText(e, new Date(e.start))} · {new Date(e.start).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })}</span>
                      <span className="block text-xs text-[var(--muted)]">{reminderText(e)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <Card title={selected.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}>
            <section aria-label="Agenda">
              {day.length === 0 ? <p className="text-sm">{data.feed.configured ? 'Nothing on this day.' : 'No calendar is set up.'}</p> : (
                <ul className="divide-y divide-[var(--border)]">
                  {day.map((e) => (
                    <li key={e.event_key ?? e.start + e.title} className="flex flex-wrap items-baseline gap-2 py-2 text-sm">
                      <span className="w-40 shrink-0 tabular-nums">{whenText(e, selected)}</span>
                      <span className="rounded bg-[var(--surface-2,#eee)] px-2 py-0.5 text-xs font-medium" data-testid="class-chip">{classLabel(e)}</span>
                      <span className="flex-1">
                        <span className="font-medium">{titleOf(e)}</span>
                        {e.status === 'tentative' && ' (tentative)'}
                        {e.location && !e.redacted && <span className="block text-[var(--muted)]">{e.location}</span>}
                        <span className="block text-xs text-[var(--muted)]">{reminderText(e)}{e.classification_basis === 'owner' ? ' · classification set by you' : ''}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </Card>
        </>
      )}
    </div>
  );
}
