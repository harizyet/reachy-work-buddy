import { ApiShapeError, request } from './client';

// The Home dashboard (docs/phase-51.md). The hub proxies core's read-only snapshot for the owner session. Every section carries its own `status`, so one failing source never hides the
// others; the client trusts that and never infers a number the server did not send. Types here describe only what the page uses.

export const HOME_SECTIONS = ['schedule', 'tasks', 'reminders', 'reviews', 'weather'] as const;
export type HomeSectionName = (typeof HOME_SECTIONS)[number];

export type SectionStatus = 'ok' | 'empty' | 'stale' | 'partial' | 'off' | 'unavailable' | 'restricted' | 'not_configured';
const STATUSES: readonly string[] = ['ok', 'empty', 'stale', 'partial', 'off', 'unavailable', 'restricted', 'not_configured'];

/** Where a card or an item opens. The web maps it to a route (features/home/links.ts). */
export interface Ref {
  screen: 'calendar' | 'tasks' | 'reminders' | 'notes' | 'meetings' | 'talk';
  id?: string;
}

export interface HomeEvent {
  id: string;
  event_key: string | null;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  classification: string | null;
  location: string | null;
  status: string;
  response: string | null;
  redacted: boolean;
  ref: Ref;
}
export interface ScheduleSection {
  status: SectionStatus;
  date?: string;
  generation?: number | null;
  snapshot_revision?: string | null;
  feed?: { configured: boolean; freshness: string; sync_state?: string; last_success_at: string | null; age_seconds: number | null; error: string | null } | null;
  feed_configured?: boolean | null;
  events?: HomeEvent[];
  all_day?: HomeEvent[];
  on_leave?: boolean;
  next_event?: HomeEvent | null;
}
export interface TaskOrigin {
  kind: 'meeting' | 'note';
  meeting_id?: string;
  meeting_title?: string | null;
  note_id?: string;
  note_title?: string | null;
}
export interface HomeTask {
  id: string;
  text: string;
  origin: TaskOrigin | null;
  ref: Ref;
}
export interface TasksSection {
  status: SectionStatus;
  total?: number;
  shown?: number;
  has_due_dates?: boolean;
  from_meetings?: number;
  from_notes?: number;
  items?: HomeTask[];
}
export interface HomeReminder {
  id: string;
  text: string;
  due_at: string;
  ref: Ref;
}
export interface RemindersSection {
  status: SectionStatus;
  upcoming_days?: number;
  counts?: { overdue: number; today: number; upcoming: number };
  overdue?: HomeReminder[];
  today?: HomeReminder[];
  upcoming?: HomeReminder[];
}
export interface ProposalItem {
  id: string;
  kind: string;
  text: string;
  note_title: string | null;
  ref: Ref;
}
export interface ActionItem {
  id: string;
  text: string;
  assignee: string | null;
  stated_time: string | null;
  meeting_title: string | null;
  ref: Ref;
}
export interface ReviewQueue<T> {
  status: SectionStatus;
  count: number;
  items: T[];
}
export interface ReviewsSection {
  status: SectionStatus;
  total?: number;
  note_proposals?: ReviewQueue<ProposalItem>;
  meeting_actions?: ReviewQueue<ActionItem>;
}
export interface WeatherSection {
  status: SectionStatus;
  error?: string;
  detail?: string;
  location?: string;
  observed_at?: string;
  fetched_at?: string;
  age_seconds?: number;
  attribution?: { name: string; url: string; license: string };
  units?: { temperature: string; precipitation: string; wind: string; humidity: string; probability: string };
  current?: { temperature: number | null; feels_like: number | null; humidity: number | null; wind_speed: number | null; precipitation: number | null; summary: string | null; raining: boolean };
  today?: { high: number | null; low: number | null; precipitation_total: number | null; precipitation_probability: number | null; summary: string | null; sunrise: string | null; sunset: string | null };
}
export interface QuickAction {
  id: string;
  label: string;
  ref: Ref;
}
export interface HomeSnapshot {
  generated_at: string;
  timezone: string;
  date: string;
  sources: Partial<Record<HomeSectionName, SectionStatus>>;
  partial: boolean;
  restricted: boolean;
  quick_actions: QuickAction[];
  schedule?: ScheduleSection;
  tasks?: TasksSection;
  reminders?: RemindersSection;
  reviews?: ReviewsSection;
  weather?: WeatherSection;
}

export interface BriefLine {
  category: string;
  status: 'confirmed' | 'pending_review' | 'info';
  text: string;
  ref: Ref | null;
  urgency: string;
}
export interface Brief {
  generated_at: string;
  mode: 'generated' | 'deterministic';
  text: string;
  lines: BriefLine[];
  narrative: string | null;
  model: string | null;
  fallback: string | null;
  partial: boolean;
  restricted: boolean;
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

export function parseHome(value: unknown): HomeSnapshot {
  if (!isObj(value) || typeof value.generated_at !== 'string' || !isObj(value.sources)) throw new ApiShapeError('home');
  for (const name of HOME_SECTIONS) {
    const section = value[name];
    if (section === undefined) continue;
    if (!isObj(section) || typeof section.status !== 'string' || !STATUSES.includes(section.status)) throw new ApiShapeError(`home.${name}`);
  }
  return value as unknown as HomeSnapshot;
}

export function parseBrief(value: unknown): Brief {
  if (!isObj(value) || typeof value.text !== 'string' || !Array.isArray(value.lines) || (value.mode !== 'generated' && value.mode !== 'deterministic')) throw new ApiShapeError('home brief');
  return value as unknown as Brief;
}

/** The whole snapshot, or only the named sections (a section refreshes on its own). */
export async function getHome(sections?: readonly HomeSectionName[], signal?: AbortSignal): Promise<HomeSnapshot> {
  const query = sections && sections.length ? `?sections=${sections.join(',')}` : '';
  return parseHome(await request(`/home${query}`, { signal }));
}

export async function briefMe(narrative: boolean, signal?: AbortSignal): Promise<Brief> {
  return parseBrief(await request('/home/brief', { method: 'POST', body: { narrative }, signal }));
}

/** Puts a refreshed section into an earlier snapshot without touching the others. */
export function mergeSection(old: HomeSnapshot, fresh: HomeSnapshot, name: HomeSectionName): HomeSnapshot {
  const sources = { ...old.sources, ...(fresh.sources[name] ? { [name]: fresh.sources[name] } : {}) };
  return { ...old, [name]: fresh[name], sources, partial: Object.values(sources).some((s) => s === 'unavailable' || s === 'partial'), generated_at: fresh.generated_at };
}
