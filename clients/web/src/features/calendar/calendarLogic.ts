import { CLASS_LABEL, type EventClass, type FeedBrief, type FeedEvent } from '../../api/calendarFeed';

// Everything the Calendar page decides, as pure functions so it can be tested without a browser: the month grid, which events fall on a day, their order, how a time is
// shown and what the sync status says. Times are read in the browser's own time zone, which is the owner's.

export const startOfDay = (d: Date): Date => new Date(d.getFullYear(), d.getMonth(), d.getDate());
export const addDays = (d: Date, n: number): Date => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
export const sameDay = (a: Date, b: Date): boolean => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/** The six weeks (Monday first) that show `month`, as 42 consecutive days. */
export function monthGrid(month: Date): Date[] {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const lead = (first.getDay() + 6) % 7;
  return Array.from({ length: 42 }, (_, i) => addDays(first, i - lead));
}

/** Whether an event touches the local day. An all-day event's end is exclusive, so one ending at midnight does not touch the day it ends on. */
export function onDay(e: FeedEvent, day: Date): boolean {
  const start = new Date(e.start).getTime();
  const end = new Date(e.end).getTime();
  const from = startOfDay(day).getTime();
  const next = addDays(startOfDay(day), 1).getTime(); // the next local midnight, so a 23- or 25-hour day is right
  return start < next && (end > from || (end === start && start >= from));
}

export const chronological = (events: FeedEvent[]): FeedEvent[] =>
  [...events].sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime() || new Date(a.end).getTime() - new Date(b.end).getTime() || a.title.localeCompare(b.title));

/** What the owner sees in the schedule: cancelled and declined events are not on it. */
export const listed = (events: FeedEvent[]): FeedEvent[] => events.filter((e) => e.status !== 'cancelled' && e.response !== 'declined');

export const eventsOn = (events: FeedEvent[], day: Date): FeedEvent[] => chronological(listed(events).filter((e) => onDay(e, day)));

export type Marker = 'meeting' | 'leave' | 'other';
/** What to mark a day with in the month grid: a meeting wins over leave, leave over anything else. */
export function dayMarkers(events: FeedEvent[], day: Date): Marker[] {
  const here = eventsOn(events, day);
  const out: Marker[] = [];
  if (here.some((e) => e.classification === 'meeting')) out.push('meeting');
  if (here.some((e) => e.classification === 'leave_or_ooo')) out.push('leave');
  if (here.some((e) => e.classification !== 'meeting' && e.classification !== 'leave_or_ooo')) out.push('other');
  return out;
}

const time = (d: Date) => d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
const dateLabel = (d: Date) => d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });

/** The time of an event on a given day: clock times for a timed one, the days covered for an all-day one. Busy entries get their interval like any timed event. */
export function whenText(e: FeedEvent, day?: Date): string {
  const start = new Date(e.start);
  const end = new Date(e.end);
  if (e.all_day) {
    const last = addDays(startOfDay(end), -1);
    return last.getTime() <= startOfDay(start).getTime() ? 'All day' : `All day, ${dateLabel(start)} to ${dateLabel(last)}`;
  }
  const crosses = !sameDay(start, end);
  const lead = day && !sameDay(start, day) ? `${dateLabel(start)} ` : '';
  if (end.getTime() <= start.getTime()) return `${lead}${time(start)}`;
  return `${lead}${time(start)}–${crosses ? `${dateLabel(end)} ` : ''}${time(end)}`;
}

export const classLabel = (e: FeedEvent): string => (e.classification ? CLASS_LABEL[e.classification as EventClass] : 'Event');
export const titleOf = (e: FeedEvent): string => (e.title_missing ? 'Untitled event' : e.title); // a missing title is never replaced by a guess; hidden ones already read "Busy"

/** Whether a recording reminder is set for the event, and if not, why, in words. */
export function reminderText(e: FeedEvent): string {
  if (e.remind) return 'Recording reminder on';
  switch (e.remind_blocked) {
    case 'declined': return 'No reminder: declined';
    case 'cancelled': return 'No reminder: cancelled';
    case 'all_day': return 'No reminder: all-day';
    case 'on_leave': return 'No reminder: you are on leave';
    case 'unconfirmed_meeting': return 'No reminder: not confirmed as a meeting';
    default:
      if (e.classification === 'busy_private') return 'No reminder: details hidden';
      if (e.classification === 'leave_or_ooo') return 'No reminder: leave';
      if (e.classification === 'personal_appointment') return 'No reminder: personal appointment';
      if (e.classification === 'unknown_timed') return 'No reminder: could not tell it is a meeting';
      return 'No reminder';
  }
}

/** The next meetings, soonest first: classified as meetings, still to start (or running) and not cancelled or declined. */
export function upcomingMeetings(events: FeedEvent[], now: Date, limit = 5): FeedEvent[] {
  return chronological(listed(events).filter((e) => e.classification === 'meeting' && new Date(e.end).getTime() > now.getTime())).slice(0, limit);
}

export const ago = (iso: string | null | undefined, now: Date): string => {
  if (!iso) return 'never';
  const s = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86_400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86_400)} d ago`;
};

const STATE_TEXT: Record<string, string> = {
  not_configured: 'No calendar set up', never: 'Not loaded yet', refreshing: 'Refreshing', ok: 'Up to date', error: 'Last refresh failed; showing the last good copy', stale: 'Out of date',
};
export const syncStateText = (f: Pick<FeedBrief, 'sync_state' | 'freshness'>): string => STATE_TEXT[f.sync_state ?? f.freshness] ?? 'Unknown';

/** Source label: the host of a link or the name of an uploaded file; the path of a link is a secret and is never shown. */
export const sourceText = (f: Pick<FeedBrief, 'configured' | 'host' | 'source'>): string =>
  !f.configured ? 'None' : f.source === 'upload' ? `Uploaded file${f.host ? ` (${f.host})` : ''}` : `Calendar link${f.host ? ` (${f.host})` : ''}`;

/** Fetched data older than the server's freshness window, or the last refresh failed: shown as cached. */
export const isCached = (f: Pick<FeedBrief, 'sync_state' | 'freshness'>): boolean => f.sync_state === 'error' || f.sync_state === 'stale' || f.freshness === 'stale';
