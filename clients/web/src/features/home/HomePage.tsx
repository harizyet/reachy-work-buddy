import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { CLASS_LABEL, type EventClass } from '../../api/calendarFeed';
import { StaleSessionError } from '../../api/client';
import {
  briefMe,
  getHome,
  mergeSection,
  type Brief,
  type HomeEvent,
  type HomeSectionName,
  type HomeSnapshot,
  type Ref,
  type SectionStatus,
  type WeatherSection,
} from '../../api/home';
import { EmptyState, ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Spinner } from '../../components/ui/Spinner';
import { hrefFor } from './links';

export const HOME_KEY = ['home'];
export const HOME_POLL_MS = 30_000;

const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
const dayTime = (iso: string) => new Date(iso).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
const n = (v: number | null | undefined, unit: string, digits = 0) => (v === null || v === undefined ? '—' : `${v.toFixed(digits)}${unit}`);
const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
const classLabel = (c: string | null) => (c && c in CLASS_LABEL ? CLASS_LABEL[c as EventClass] : 'Event');

function Link({ to, children, className = '' }: { to: Ref | null | undefined; children: ReactNode; className?: string }) {
  return <a href={hrefFor(to)} className={`underline-offset-2 hover:underline ${className}`}>{children}</a>;
}

/** A card for one section: its own refresh, and an honest line for every state a source can be in. */
function Section({ name, title, eyebrow, status, onRefresh, busy, note, off, children }: {
  name: HomeSectionName;
  title: string;
  eyebrow: string;
  status: SectionStatus | undefined;
  onRefresh: (name: HomeSectionName) => void;
  busy: boolean;
  note?: string | null;
  off?: string;
  children: ReactNode;
}) {
  let body: ReactNode = children;
  if (status === undefined) body = <EmptyState>Not loaded yet.</EmptyState>;
  else if (status === 'restricted') body = <EmptyState>Not shown in this context.</EmptyState>;
  else if (status === 'unavailable') body = <p role="status" className="py-2 text-sm text-[var(--bad)]">This could not be read just now. Your other sections are not affected.</p>;
  else if (status === 'off') body = <EmptyState>{off ?? 'This feature is turned off.'}</EmptyState>;
  return (
    <section className="flex flex-col rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4" aria-label={title}>
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <span className="block text-[0.7rem] font-medium tracking-widest text-[var(--muted)]">{eyebrow}</span>
          <h2 className="text-base font-semibold">{title}</h2>
        </div>
        <Button variant="secondary" className="shrink-0" disabled={busy} aria-label={`Refresh ${title.toLowerCase()}`} onClick={() => onRefresh(name)}>
          {busy ? 'Refreshing…' : 'Refresh'}
        </Button>
      </div>
      {note && <p role="status" className="mb-2 text-sm text-[var(--warn)]">▲ {note}</p>}
      {body}
    </section>
  );
}

function EventRow({ e }: { e: HomeEvent }) {
  return (
    <li className="flex items-baseline justify-between gap-3 py-1.5">
      <Link to={e.ref} className="min-w-0 break-words">
        <span className="font-medium">{e.title}</span>
        {e.location && <span className="text-[var(--muted)]"> · {e.location}</span>}
      </Link>
      <span className="shrink-0 text-right text-xs text-[var(--muted)]">
        {e.all_day ? classLabel(e.classification) : `${time(e.start)}–${time(e.end)}`}
        {!e.all_day && e.classification && e.classification !== 'meeting' && ` · ${classLabel(e.classification)}`}
      </span>
    </li>
  );
}

function ScheduleCard(props: { snapshot: HomeSnapshot; onRefresh: (n: HomeSectionName) => void; busy: boolean }) {
  const s = props.snapshot.schedule;
  const stale = s?.status === 'stale' || s?.feed?.freshness === 'stale';
  return (
    <Section name="schedule" title="Today's schedule" eyebrow="CALENDAR" status={s?.status} onRefresh={props.onRefresh} busy={props.busy} note={stale ? 'The calendar may be out of date: its last sync is old.' : null}>
      {s && (
        <>
          {s.on_leave && <p className="mb-1 text-sm font-medium">You are on leave today.</p>}
          {!!s.all_day?.length && <ul className="divide-y divide-[var(--border)]">{s.all_day.map((e) => <EventRow key={e.id} e={e} />)}</ul>}
          {!!s.events?.length && <ul className="divide-y divide-[var(--border)]">{s.events.map((e) => <EventRow key={e.id} e={e} />)}</ul>}
          {s.status === 'empty' && (
            <EmptyState>{s.feed_configured === false ? <>No calendar is connected. Add one under <a className="underline" href="#/settings/accounts">Settings &gt; Accounts</a>.</> : 'Nothing on your calendar today.'}</EmptyState>
          )}
          {s.next_event && (
            <p className="mt-2 border-t border-[var(--border)] pt-2 text-sm">
              <span className="text-[var(--muted)]">Next: </span>
              <Link to={s.next_event.ref}>{s.next_event.title}</Link> <span className="text-[var(--muted)]">{dayTime(s.next_event.start)}</span>
            </p>
          )}
          <p className="mt-2 text-sm"><Link to={{ screen: 'calendar' }} className="text-[var(--accent)]">Open calendar</Link></p>
        </>
      )}
    </Section>
  );
}

function TasksCard(props: { snapshot: HomeSnapshot; onRefresh: (n: HomeSectionName) => void; busy: boolean }) {
  const t = props.snapshot.tasks;
  return (
    <Section name="tasks" title="Open tasks" eyebrow="TO DO" status={t?.status} onRefresh={props.onRefresh} busy={props.busy}>
      {t && (
        <>
          {t.status === 'empty' ? <EmptyState>No open tasks.</EmptyState> : (
            <>
              <p className="mb-1 text-sm text-[var(--muted)]">
                {plural(t.total ?? 0, 'open task')}{t.from_meetings ? ` · ${t.from_meetings} from meetings` : ''} · tasks have no due dates
              </p>
              <ul className="divide-y divide-[var(--border)]">
                {(t.items ?? []).map((x) => (
                  <li key={x.id} className="py-1.5 text-sm">
                    <Link to={x.ref} className="break-words">{x.text}</Link>
                    {x.origin && <span className="block text-xs text-[var(--muted)]">{x.origin.kind === 'meeting' ? `From meeting${x.origin.meeting_title ? `: ${x.origin.meeting_title}` : ''}` : `From note${x.origin.note_title ? `: ${x.origin.note_title}` : ''}`}</span>}
                  </li>
                ))}
              </ul>
              {(t.total ?? 0) > (t.shown ?? 0) && <p className="mt-1 text-xs text-[var(--muted)]">and {(t.total ?? 0) - (t.shown ?? 0)} more</p>}
            </>
          )}
          <p className="mt-2 text-sm"><Link to={{ screen: 'tasks' }} className="text-[var(--accent)]">Open to do</Link></p>
        </>
      )}
    </Section>
  );
}

function RemindersCard(props: { snapshot: HomeSnapshot; onRefresh: (n: HomeSectionName) => void; busy: boolean }) {
  const r = props.snapshot.reminders;
  const groups: [string, typeof r extends undefined ? never : NonNullable<typeof r>['today']][] = r ? [['Overdue', r.overdue], ['Today', r.today], ['Coming up', r.upcoming]] : [];
  return (
    <Section name="reminders" title="Reminders" eyebrow="PLANNER" status={r?.status} onRefresh={props.onRefresh} busy={props.busy}>
      {r && (
        <>
          {r.status === 'empty' && <EmptyState>No reminders due today or in the next {r.upcoming_days ?? 7} days.</EmptyState>}
          {groups.map(([label, items]) =>
            items && items.length ? (
              <div key={label} className="mb-2">
                <h3 className={`text-xs font-medium tracking-wide ${label === 'Overdue' ? 'text-[var(--bad)]' : 'text-[var(--muted)]'}`}>{label.toUpperCase()}</h3>
                <ul>
                  {items.map((x) => (
                    <li key={x.id} className="flex items-baseline justify-between gap-3 py-1 text-sm">
                      <Link to={x.ref} className="min-w-0 break-words">{x.text}</Link>
                      <span className="shrink-0 text-xs text-[var(--muted)]">{label === 'Coming up' ? dayTime(x.due_at) : time(x.due_at)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null,
          )}
          <p className="mt-1 text-sm"><Link to={{ screen: 'reminders' }} className="text-[var(--accent)]">Open reminders</Link></p>
        </>
      )}
    </Section>
  );
}

function ReviewsCard(props: { snapshot: HomeSnapshot; onRefresh: (n: HomeSectionName) => void; busy: boolean }) {
  const v = props.snapshot.reviews;
  const notes = v?.note_proposals;
  const actions = v?.meeting_actions;
  return (
    <Section
      name="reviews" title="Waiting for your review" eyebrow="SUGGESTIONS" status={v?.status} onRefresh={props.onRefresh} busy={props.busy}
      off="Note and meeting processing are turned off." note={v?.status === 'partial' ? 'One of the review lists could not be read, so these counts may be incomplete.' : null}
    >
      {v && (
        <>
          <p className="mb-2 text-xs text-[var(--muted)]">Suggestions written by the local model. Nothing here is a task, reminder or note until you accept it.</p>
          {v.status === 'empty' && <EmptyState>No suggestions waiting.</EmptyState>}
          {notes && notes.status === 'ok' && (
            <div className="mb-2">
              <h3 className="text-xs font-medium tracking-wide text-[var(--muted)]">{plural(notes.count, 'NOTE SUGGESTION').toUpperCase()}</h3>
              <ul>{notes.items.map((x) => <li key={x.id} className="py-1 text-sm"><Link to={x.ref} className="break-words">{x.text}</Link>{x.note_title && <span className="block text-xs text-[var(--muted)]">From note: {x.note_title}</span>}</li>)}</ul>
              {notes.count > notes.items.length && <p className="text-xs text-[var(--muted)]">and {notes.count - notes.items.length} more</p>}
            </div>
          )}
          {actions && actions.status === 'ok' && (
            <div className="mb-2">
              <h3 className="text-xs font-medium tracking-wide text-[var(--muted)]">{plural(actions.count, 'MEETING ACTION CANDIDATE').toUpperCase()}</h3>
              <ul>{actions.items.map((x) => <li key={x.id} className="py-1 text-sm"><Link to={x.ref} className="break-words">{x.text}</Link>{x.meeting_title && <span className="block text-xs text-[var(--muted)]">From meeting: {x.meeting_title}{x.assignee ? ` · ${x.assignee}` : ''}</span>}</li>)}</ul>
              {actions.count > actions.items.length && <p className="text-xs text-[var(--muted)]">and {actions.count - actions.items.length} more</p>}
            </div>
          )}
        </>
      )}
    </Section>
  );
}

function safeUrl(url: string | undefined): string | null {
  return url && url.startsWith('https://') ? url : null;
}

export function weatherLines(w: WeatherSection): string[] {
  const u = w.units;
  if (!w.current || !w.today || !u) return [];
  const lines = [`${w.current.summary ?? 'Conditions unavailable'} · ${n(w.current.temperature, u.temperature)}${w.current.feels_like !== null ? ` (feels like ${n(w.current.feels_like, u.temperature)})` : ''}`];
  lines.push(`Today ${n(w.today.low, u.temperature)} to ${n(w.today.high, u.temperature)}${w.today.summary ? ` · ${w.today.summary}` : ''}`);
  if (w.today.precipitation_total !== null) {
    lines.push(`Rain today: ${n(w.today.precipitation_total, ` ${u.precipitation}`, 1)}${w.today.precipitation_probability !== null ? ` · up to ${n(w.today.precipitation_probability, u.probability)} chance` : ''}`);
  }
  return lines;
}

function WeatherCard(props: { snapshot: HomeSnapshot; onRefresh: (n: HomeSectionName) => void; busy: boolean }) {
  const w = props.snapshot.weather;
  const link = safeUrl(w?.attribution?.url);
  return (
    <Section
      name="weather" title="Weather" eyebrow={w?.location ? w.location.toUpperCase() : 'WEATHER'} status={w?.status} onRefresh={props.onRefresh} busy={props.busy}
      off="Weather is turned off."
      note={w?.status === 'stale' ? `Out of date: last updated ${plural(Math.max(1, Math.round((w.age_seconds ?? 0) / 60)), 'minute')} ago.` : null}
    >
      {w?.status === 'not_configured' && <EmptyState>Set your location under <a className="underline" href="#/settings/assistant">Settings &gt; Assistant</a> to see the weather.</EmptyState>}
      {(w?.status === 'ok' || w?.status === 'stale') && (
        <>
          <ul className="space-y-0.5 text-sm">{weatherLines(w).map((l) => <li key={l}>{l}</li>)}</ul>
          <p className="mt-2 text-xs text-[var(--muted)]">
            Observed {w.observed_at ? time(w.observed_at) : '—'}
            {link ? <> · <a className="underline" href={link} target="_blank" rel="noreferrer noopener">Weather data by {w.attribution?.name}</a> ({w.attribution?.license})</> : ` · Weather data by ${w.attribution?.name ?? 'the provider'}`}
          </p>
        </>
      )}
    </Section>
  );
}

function QuickActions({ snapshot }: { snapshot: HomeSnapshot }) {
  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4" aria-label="Quick actions">
      <span className="block text-[0.7rem] font-medium tracking-widest text-[var(--muted)]">SHORTCUTS</span>
      <h2 className="mb-3 text-base font-semibold">Quick actions</h2>
      {snapshot.quick_actions.length === 0 ? <EmptyState>None right now.</EmptyState> : (
        <ul className="flex flex-wrap gap-2">
          {snapshot.quick_actions.map((q) => (
            <li key={q.id}>
              <a href={hrefFor(q.ref)} className="inline-block rounded-md border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--hover)]">{q.label}</a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const STATUS_LABEL = { confirmed: 'Confirmed', pending_review: 'Suggestion', info: 'Info' } as const;

function BriefPanel({ brief, onClose }: { brief: Brief; onClose: () => void }) {
  return (
    <section className="mb-4 rounded-lg border border-[var(--accent)] bg-[var(--surface)] p-4" aria-label="Today's briefing">
      <div className="mb-2 flex items-start justify-between gap-2">
        <h2 className="text-base font-semibold">Brief for today</h2>
        <Button variant="secondary" onClick={onClose}>Close</Button>
      </div>
      {brief.mode === 'generated' && brief.narrative ? (
        <>
          <p className="whitespace-pre-wrap text-sm">{brief.narrative}</p>
          <p className="mt-1 text-xs text-[var(--muted)]">Reworded by the local model{brief.model ? ` (${brief.model})` : ''} from the lines below, which are the record. Check them if anything matters.</p>
        </>
      ) : (
        <p className="text-xs text-[var(--muted)]" role="status">
          {brief.fallback && brief.fallback !== 'nothing_to_reword' ? 'A written summary was not available, so this is the plain briefing.' : 'Plain briefing.'}
        </p>
      )}
      {brief.partial && <p className="mt-1 text-sm text-[var(--warn)]">▲ Some sources could not be read, so this briefing may be incomplete.</p>}
      <ul className="mt-2 divide-y divide-[var(--border)]">
        {brief.lines.length === 0 && <li className="py-2 text-sm">Nothing to report for today.</li>}
        {brief.lines.map((l, i) => (
          <li key={i} className="flex items-baseline gap-2 py-1.5 text-sm">
            <span className={`shrink-0 rounded px-1.5 py-0.5 text-[0.65rem] font-medium ${l.status === 'pending_review' ? 'bg-[var(--warn-bg)] text-[var(--warn)]' : 'bg-[var(--hover)] text-[var(--muted)]'}`}>{STATUS_LABEL[l.status]}</span>
            {l.ref ? <Link to={l.ref} className="min-w-0 break-words">{l.text}</Link> : <span className="min-w-0 break-words">{l.text}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function HomePage() {
  const client = useQueryClient();
  const home = useQuery({ queryKey: HOME_KEY, queryFn: ({ signal }) => getHome(undefined, signal), refetchInterval: HOME_POLL_MS, refetchOnWindowFocus: true, retry: false });
  const [busy, setBusy] = useState<Partial<Record<HomeSectionName, boolean>>>({});
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [brief, setBrief] = useState<Brief | null>(null);
  const briefing = useMutation({
    mutationFn: () => briefMe(true),
    onSuccess: setBrief,
  });

  // A section refreshes on its own: only its card changes, and the others keep what they show.
  const refreshSection = async (name: HomeSectionName) => {
    setBusy((b) => ({ ...b, [name]: true }));
    setRefreshError(null);
    try {
      const fresh = await getHome([name]);
      client.setQueryData<HomeSnapshot>(HOME_KEY, (old) => (old ? mergeSection(old, fresh, name) : fresh));
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setRefreshError(e instanceof Error ? e.message : 'Refresh failed');
    } finally {
      setBusy((b) => ({ ...b, [name]: false }));
    }
  };

  const [clock, setClock] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 60_000);
    return () => clearInterval(t);
  }, []);

  const data = home.data;
  const greeting = clock.getHours() < 12 ? 'Good morning' : clock.getHours() < 18 ? 'Good afternoon' : 'Good evening';
  const common = (name: HomeSectionName) => ({ onRefresh: (x: HomeSectionName) => void refreshSection(x), busy: !!busy[name] });

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <span className="block text-[0.7rem] font-medium tracking-widest text-[var(--muted)]">{clock.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' }).toUpperCase()}</span>
          <h1 className="text-2xl font-semibold">Home</h1>
          <p className="text-sm text-[var(--muted)]">{greeting}. Here is what is on your plate.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-[var(--muted)]" role="status">
            {data ? `Updated ${new Date(data.generated_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}${home.isFetching ? ' · refreshing' : ''}` : ''}
            {home.error && data ? ' · may be out of date' : ''}
          </p>
          <Button onClick={() => briefing.mutate()} disabled={briefing.isPending || !data || data.restricted}>{briefing.isPending ? 'Preparing…' : 'Brief me on today'}</Button>
        </div>
      </div>
      {briefing.error && !(briefing.error instanceof StaleSessionError) && <div className="mb-4"><ErrorState message={briefing.error.message} onRetry={() => briefing.mutate()} /></div>}
      {brief && <BriefPanel brief={brief} onClose={() => setBrief(null)} />}
      {refreshError && <p role="alert" className="mb-3 text-sm text-[var(--bad)]">{refreshError}</p>}
      {home.isPending && <Spinner label="Loading Home" />}
      {home.error && !data && !(home.error instanceof StaleSessionError) && <ErrorState message={home.error.message} onRetry={() => void home.refetch()} />}
      {data?.partial && <p role="status" className="mb-3 text-sm text-[var(--warn)]">▲ Some sources could not be read. The sections that did load are accurate; the others say what is missing.</p>}
      {data && (
        <div className="grid gap-4 md:grid-cols-2">
          <ScheduleCard snapshot={data} {...common('schedule')} />
          <RemindersCard snapshot={data} {...common('reminders')} />
          <TasksCard snapshot={data} {...common('tasks')} />
          <ReviewsCard snapshot={data} {...common('reviews')} />
          <WeatherCard snapshot={data} {...common('weather')} />
          <QuickActions snapshot={data} />
        </div>
      )}
      <p className="mt-6 text-sm text-[var(--muted)]">Looking for the robot, models and services? That is now <a className="underline" href="#/system">System</a>.</p>
    </div>
  );
}
