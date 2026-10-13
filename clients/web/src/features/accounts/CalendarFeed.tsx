import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import {
  CLASS_LABEL,
  EVENT_CLASSES,
  clearOverride,
  feedEvents,
  feedProblem,
  getFeed,
  refreshFeed,
  removeFeed,
  saveFeedConfig,
  saveFeedUrl,
  setOverride,
  uploadFeedFile,
  type EventClass,
  type FeedEvent,
  type FeedStatus,
} from '../../api/calendarFeed';
import { StaleSessionError } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Spinner } from '../../components/ui/Spinner';
import { selectClass } from '../settings/fields';

const KEY = ['calendar-feed'];
const SCHEDULE = ['calendar-schedule'];
const FRESHNESS: Record<FeedStatus['freshness'], string> = {
  not_configured: 'Not set up',
  never: 'Not loaded yet',
  fresh: 'Up to date',
  stale: 'Out of date: the last good copy is being used',
};

const problem = (e: unknown) => (e instanceof Error ? (feedProblem(e.message) !== 'The calendar could not be loaded.' ? feedProblem(e.message) : e.message) : 'Something went wrong');

const when = (e: FeedEvent) => {
  const start = new Date(e.start);
  const end = new Date(e.end);
  const day = start.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
  if (e.all_day) {
    const last = new Date(end.getTime() - 24 * 3_600_000); // an all-day event's end is exclusive
    return last.toDateString() === start.toDateString() ? day : `${day} to ${last.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })}`;
  }
  const time = (d: Date) => d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  return `${day}, ${time(start)}${end > start ? `–${time(end)}` : ''}`;
};

// The feed URL is write-only: it is sent once and only its host is shown back.
export function CalendarFeed() {
  const client = useQueryClient();
  const status = useQuery({ queryKey: KEY, queryFn: ({ signal }) => getFeed(signal), refetchOnMount: 'always', refetchInterval: 20_000, retry: false });
  const [message, setMessage] = useState('');
  const [url, setUrl] = useState('');
  const done = (s: FeedStatus) => client.setQueryData(KEY, s);
  const fail = (e: unknown) => !(e instanceof StaleSessionError) && setMessage(problem(e));
  const save = useMutation({
    mutationFn: saveFeedUrl,
    onSuccess: (s) => {
      setUrl('');
      done(s);
      setMessage(s.error ? feedProblem(s.error) : 'Calendar feed saved and loaded.');
      void client.invalidateQueries({ queryKey: ['calendar-feed-events'] });
      void client.invalidateQueries({ queryKey: SCHEDULE });
    },
    onError: fail,
  });
  const upload = useMutation({
    mutationFn: uploadFeedFile,
    onSuccess: (s) => {
      done(s);
      setMessage(`Calendar file loaded: ${s.event_count} events.`);
      void client.invalidateQueries({ queryKey: ['calendar-feed-events'] });
      void client.invalidateQueries({ queryKey: SCHEDULE });
    },
    onError: fail,
  });
  const refresh = useMutation({
    mutationFn: refreshFeed,
    onSuccess: (s) => {
      done(s);
      setMessage(s.error ? feedProblem(s.error) : 'Refreshed.');
      void client.invalidateQueries({ queryKey: ['calendar-feed-events'] });
      void client.invalidateQueries({ queryKey: SCHEDULE });
    },
    onError: fail,
  });
  const remove = useMutation({ mutationFn: removeFeed, onSuccess: (s) => { done(s); setMessage('Calendar feed removed.'); void client.invalidateQueries({ queryKey: SCHEDULE }); void client.invalidateQueries({ queryKey: ['calendar-feed-events'] }); }, onError: fail });
  const data = status.data;
  return (
    <Card eyebrow="CALENDAR" title="Calendar feed (read-only)">
      <p className="mb-2 text-sm text-[var(--muted)]">
        Reachy reads meetings from an iCalendar (.ics) link and reminds you on your phone shortly before each real meeting, with a button that opens the recorder. It never changes your
        calendar. The link is a secret: it is stored encrypted, sent once, and never shown again.
      </p>
      <p role="status" className="min-h-5 text-sm">{message || (status.error && !(status.error instanceof StaleSessionError) ? status.error.message : '')}</p>
      {status.isPending && <Spinner label="Loading calendar feed" />}
      {data && (
        <>
          <p className="text-sm" aria-label="Calendar feed status">
            {data.configured ? `${data.source === 'upload' ? 'Uploaded file' : 'Feed from'} ${data.host ?? 'a saved address'}. ${FRESHNESS[data.freshness]}` : 'No feed set up.'}
            {data.last_success_at && ` Last loaded ${new Date(data.last_success_at).toLocaleString()}.`}
            {data.error && ` ${feedProblem(data.error)}`}
            {data.configured && data.freshness !== 'never' && ` ${data.event_count} events in the next ${data.config.horizon_days} days.`}
          </p>
          <form
            className="my-3 flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setMessage('');
              save.mutate(url.trim());
            }}
          >
            <label className="block flex-1 text-sm">
              Calendar link (https:// or webcal://)
              <input type="password" autoComplete="off" required maxLength={2048} className={selectClass} value={url} onChange={(e) => setUrl(e.target.value)} placeholder={data.configured ? 'Paste a new link to replace the saved one' : 'https://…/basic.ics'} />
            </label>
            <Button type="submit" disabled={save.isPending}>{data.configured ? 'Replace link' : 'Save link'}</Button>
            {data.configured && <Button variant="secondary" disabled={refresh.isPending} onClick={() => refresh.mutate()}>Refresh now</Button>}
            {data.configured && <Button variant="secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>Remove feed</Button>}
          </form>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <label className="text-sm">
              Or upload an .ics file (replaces the calendar at once; a file that cannot be read changes nothing)
              <input
                type="file"
                accept=".ics,text/calendar"
                aria-label="Upload an ICS file"
                className="mt-1 block text-sm"
                disabled={upload.isPending}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = '';
                  if (file) { setMessage(''); upload.mutate(file); }
                }}
              />
            </label>
            {data.source === 'upload' && <span className="text-sm">Source: uploaded file {data.host}</span>}
          </div>
          <Settings status={data} onSaved={(s) => { done(s); setMessage('Settings saved.'); }} onError={fail} />
          {data.configured && <Schedule status={data} onChanged={done} onError={fail} />}
        </>
      )}
    </Card>
  );
}

function Settings({ status, onSaved, onError }: { status: FeedStatus; onSaved: (s: FeedStatus) => void; onError: (e: unknown) => void }) {
  const c = status.config;
  const [lead, setLead] = useState(String(c.lead_minutes));
  const [every, setEvery] = useState(String(c.refresh_minutes));
  const [emails, setEmails] = useState(c.rules.owner_emails.join(', '));
  const [keywords, setKeywords] = useState(c.rules.remind_keyword_meetings);
  const [suppress, setSuppress] = useState(c.rules.leave_suppresses_meetings);
  return (
    <form
      className="mb-3 grid gap-2 md:grid-cols-2"
      aria-label="Calendar feed settings"
      onSubmit={(e) => {
        e.preventDefault();
        saveFeedConfig({
          ...c,
          lead_minutes: Number(lead),
          refresh_minutes: Number(every),
          rules: { ...c.rules, owner_emails: emails.split(',').map((a) => a.trim()).filter(Boolean), remind_keyword_meetings: keywords, leave_suppresses_meetings: suppress },
        }).then(onSaved, onError);
      }}
    >
      <label className="block text-sm">
        Remind me this many minutes before a meeting
        <input type="number" min={1} max={120} required className={selectClass} value={lead} onChange={(e) => setLead(e.target.value)} />
      </label>
      <label className="block text-sm">
        Check the calendar every (minutes)
        <input type="number" min={5} max={1440} required className={selectClass} value={every} onChange={(e) => setEvery(e.target.value)} />
      </label>
      <label className="block text-sm md:col-span-2">
        Your email addresses (so Reachy can tell you from other guests and see your own answer)
        <input type="text" className={selectClass} value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="me@example.com, me@work.example" />
      </label>
      <label className="flex items-center gap-2 text-sm md:col-span-2">
        <input type="checkbox" checked={keywords} onChange={(e) => setKeywords(e.target.checked)} />
        Also remind me for events whose title says meeting, sync, call and the like, even with no guests or call link
      </label>
      <label className="flex items-center gap-2 text-sm md:col-span-2">
        <input type="checkbox" checked={suppress} onChange={(e) => setSuppress(e.target.checked)} />
        No reminders for meetings that fall on a day I am on leave (off by default: a leave day does not silence meetings)
      </label>
      <div className="md:col-span-2"><Button type="submit">Save settings</Button></div>
    </form>
  );
}

function Schedule({ status, onChanged, onError }: { status: FeedStatus; onChanged: (s: FeedStatus) => void; onError: (e: unknown) => void }) {
  const events = useQuery({
    queryKey: ['calendar-feed-events', status.generation, status.last_success_at, JSON.stringify(status.overrides), status.config.rules],
    queryFn: ({ signal }) => {
      const start = new Date();
      start.setHours(0, 0, 0, 0);
      return feedEvents(start, new Date(start.getTime() + 7 * 24 * 3_600_000), signal);
    },
    retry: false,
  });
  return (
    <section aria-label="Next 7 days">
      <h3 className="font-medium">Next 7 days</h3>
      {events.isPending && <Spinner label="Loading events" />}
      {events.error && !(events.error instanceof StaleSessionError) && <p className="text-sm">{events.error.message}</p>}
      {events.data && events.data.length === 0 && <p className="text-sm">Nothing on the feed in the next 7 days.</p>}
      <ul className="divide-y divide-[var(--border)]">
        {events.data?.map((e) => (
          <li key={e.event_key ?? e.start + e.title} className="flex flex-wrap items-center gap-2 py-2 text-sm">
            <span className="rounded bg-[var(--surface-2,#eee)] px-2 py-0.5 text-xs font-medium" data-testid="class-chip">{e.classification ? CLASS_LABEL[e.classification] : 'Event'}</span>
            <span className="flex-1">
              <span className="font-medium">{e.title_missing ? 'Untitled event' : e.title}</span>
              {e.status === 'tentative' && ' (tentative)'}
              <span className="block text-[var(--muted)]">
                {when(e)}
                {e.remind ? ' · reminder on' : e.remind_blocked === 'declined' ? ' · declined' : e.remind_blocked === 'on_leave' ? ' · skipped, you are on leave' : ''}
                {e.classification_basis === 'owner' ? ' · set by you' : ''}
              </span>
            </span>
            {e.source === 'ics' && e.event_key && (
              <select
                aria-label={`Classification of ${e.title_missing ? 'untitled event' : e.title}`}
                className={selectClass}
                value={e.classification ?? ''}
                onChange={(ev) => {
                  const next = ev.target.value as EventClass;
                  (next ? setOverride(e.event_key as string, next) : clearOverride(e.event_key as string)).then(onChanged, onError);
                }}
              >
                {e.classification_basis === 'owner' && <option value="">Automatic (remove my choice)</option>}
                {EVENT_CLASSES.map((c) => <option key={c} value={c}>{CLASS_LABEL[c]}</option>)}
              </select>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-1 text-xs text-[var(--muted)]">Changing a classification applies to this occurrence only. Hidden (busy) entries keep their details hidden whatever you choose.</p>
    </section>
  );
}
