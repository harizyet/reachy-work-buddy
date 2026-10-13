import { ApiShapeError, request } from './client';

// The owner's read-only calendar feed (ADR 0035). The feed URL is a credential: it is sent once and never comes back, only the host does. Classification is decided by the
// server, deterministically; this file only shapes requests and checks responses, so the web and the Android app show the same thing.

export type EventClass = 'meeting' | 'personal_appointment' | 'leave_or_ooo' | 'all_day' | 'unknown_timed' | 'busy_private';
export const EVENT_CLASSES: readonly EventClass[] = ['meeting', 'personal_appointment', 'leave_or_ooo', 'all_day', 'unknown_timed', 'busy_private'];

export const CLASS_LABEL: Record<EventClass, string> = {
  meeting: 'Meeting',
  personal_appointment: 'Appointment',
  leave_or_ooo: 'Leave',
  all_day: 'All day',
  unknown_timed: 'Timed event',
  busy_private: 'Busy',
};

export interface FeedRules {
  owner_emails: string[];
  remind_keyword_meetings: boolean;
  leave_suppresses_meetings: boolean;
}
export interface FeedConfig {
  refresh_minutes: number;
  lead_minutes: number;
  horizon_days: number;
  device_horizon_hours: number;
  timezone: string | null;
  rules: FeedRules & Record<string, unknown>;
}
export interface FeedStatus {
  configured: boolean;
  host: string | null;
  freshness: 'not_configured' | 'never' | 'fresh' | 'stale';
  last_success_at: string | null;
  last_attempt_at: string | null;
  age_seconds: number | null;
  error: string | null;
  consecutive_failures: number;
  event_count: number;
  truncated: boolean;
  config: FeedConfig;
  overrides: Record<string, string>;
}
export interface FeedEvent {
  title: string;
  start: string;
  end: string;
  location: string | null;
  all_day: boolean;
  classification: EventClass | null;
  classification_basis: 'explicit' | 'rule' | 'owner' | null;
  classification_reasons: string[];
  status: 'confirmed' | 'tentative' | 'cancelled';
  response: string | null;
  redacted: boolean;
  title_missing: boolean;
  source: string;
  event_key: string | null;
  series_key: string | null;
  recurring: boolean;
  remind: boolean;
  remind_blocked: string | null;
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

function parseStatus(value: unknown): FeedStatus {
  if (!isObject(value) || typeof value.configured !== 'boolean' || typeof value.freshness !== 'string' || !isObject(value.config) || !isObject(value.overrides)) throw new ApiShapeError('calendar feed status');
  return value as unknown as FeedStatus;
}

function parseEvents(value: unknown): FeedEvent[] {
  if (!Array.isArray(value)) throw new ApiShapeError('calendar events');
  return value.map((item) => {
    if (!isObject(item) || typeof item.title !== 'string' || typeof item.start !== 'string' || typeof item.end !== 'string') throw new ApiShapeError('calendar event');
    return item as unknown as FeedEvent;
  });
}

export const getFeed = async (signal?: AbortSignal): Promise<FeedStatus> => parseStatus(await request('/calendar-feed', { signal }));
/** Sets the feed URL (write-only) and downloads once so the owner sees whether it works. */
export const saveFeedUrl = async (url: string): Promise<FeedStatus> => parseStatus(await request('/calendar-feed', { method: 'PUT', body: { url } }));
export const saveFeedConfig = async (config: Partial<FeedConfig>): Promise<FeedStatus> => parseStatus(await request('/calendar-feed', { method: 'PUT', body: { config } }));
export const removeFeed = async (): Promise<FeedStatus> => parseStatus(await request('/calendar-feed', { method: 'DELETE' }));
export const refreshFeed = async (): Promise<FeedStatus> => parseStatus(await request('/calendar-feed/refresh', { method: 'POST' }));
export const setOverride = async (key: string, classification: EventClass): Promise<FeedStatus> =>
  parseStatus(await request('/calendar-feed/overrides', { method: 'PUT', body: { key, classification } }));
export const clearOverride = async (key: string): Promise<FeedStatus> => parseStatus(await request('/calendar-feed/overrides', { method: 'DELETE', body: { key } }));
export const feedEvents = async (start: Date, end: Date, signal?: AbortSignal): Promise<FeedEvent[]> =>
  parseEvents(await request(`/calendar-feed/events?${new URLSearchParams({ start: start.toISOString(), end: end.toISOString() })}`, { signal }));

/** Fixed codes from the server, in words. None of them contains the URL. */
export const FEED_ERRORS: Record<string, string> = {
  unsafe_url: 'That address is not allowed. Use the https:// link from your calendar (a webcal:// link also works), with no user name or password in it.',
  unsafe_address: 'That address points at a private or internal network, which is not allowed.',
  dns_failed: 'The address could not be looked up.',
  connect_failed: 'The calendar server could not be reached.',
  timeout: 'The calendar server took too long to answer.',
  not_calendar: 'The address did not return a calendar (an .ics file).',
  too_large: 'The calendar is larger than the 10 MB limit.',
  redirect_refused: 'The address redirected somewhere that is not allowed.',
  parse_failed: 'The calendar could not be read.',
  internal_error: 'Something went wrong reading the calendar.',
  invalid_request: 'That value is not valid.',
  calendar_feed_unavailable: 'The calendar feed is not available on this installation.',
};
export const feedProblem = (code: string | null | undefined): string =>
  !code ? '' : FEED_ERRORS[code] ?? (/^http_\d{3}$/.test(code) ? `The calendar server answered ${code.slice(5)}.` : 'The calendar could not be loaded.');
