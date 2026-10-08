import { request } from './client';
import {
  parseBusy,
  parseCalendars,
  parseCredentials,
  parseDesktopStart,
  parseEvents,
  parseGoogleStatus,
  parseMessageBody,
  parseMessages,
  type CalendarInfo,
  type CalendarEvent,
  type CredentialRecord,
  type DesktopStart,
  type GoogleStatus,
  type MailMessage,
} from './types';

const ROOT = '/settings/accounts/google';
type Cap = 'gmail' | 'calendar';

export const getGoogle = async (signal?: AbortSignal): Promise<GoogleStatus> => parseGoogleStatus(await request(ROOT, { signal }));
export const completeGoogle = async (): Promise<GoogleStatus> => parseGoogleStatus(await request(`${ROOT}/complete`, { method: 'POST' }));
export const configureGoogle = async (body: unknown): Promise<GoogleStatus> => parseGoogleStatus(await request(`${ROOT}/configure`, { method: 'PUT', body }));
export const testGoogle = async (capability: Cap): Promise<GoogleStatus> => parseGoogleStatus(await request(`${ROOT}/test`, { method: 'POST', body: { capability } }));
export const disconnectGoogle = async (): Promise<{ status: GoogleStatus; revoked: boolean }> => {
  const r = (await request(`${ROOT}/disconnect`, { method: 'POST' })) as { status?: unknown; revocation?: unknown };
  return { status: parseGoogleStatus(r.status), revoked: r.revocation === 'revoked' };
};
/** Web clients: returns the Google sign-in address (the caller checks its origin before navigating). */
export const connectGoogle = async (capability: Cap): Promise<string> => {
  const r = (await request(`${ROOT}/connect`, { method: 'POST', body: { capability } })) as { authorization_url?: unknown };
  return typeof r.authorization_url === 'string' ? r.authorization_url : '';
};
export const startDesktop = async (capability: Cap): Promise<DesktopStart> =>
  parseDesktopStart(await request(`${ROOT}/desktop/start`, { method: 'POST', body: { capability } }));
export const listCalendars = async (signal?: AbortSignal): Promise<CalendarInfo[]> => parseCalendars(await request(`${ROOT}/calendars`, { signal }));
export const saveCalendars = async (ids: string[]): Promise<GoogleStatus> => parseGoogleStatus(await request(`${ROOT}/selection`, { method: 'PUT', body: { calendar_ids: ids } }));
export const upcomingEvents = async (start: Date, end: Date): Promise<CalendarEvent[]> =>
  parseEvents(await request(`${ROOT}/events?${new URLSearchParams({ start: start.toISOString(), end: end.toISOString() })}`));
export const busyTimes = async (start: Date, end: Date) =>
  parseBusy(await request(`${ROOT}/free-busy?${new URLSearchParams({ start: start.toISOString(), end: end.toISOString() })}`));
export const searchMail = async (query: string): Promise<MailMessage[]> => parseMessages(await request(`${ROOT}/messages?${new URLSearchParams({ query })}`));
export const readMail = async (id: string): Promise<string> => parseMessageBody(await request(`${ROOT}/messages/${encodeURIComponent(id)}`));

export const listCredentials = async (signal?: AbortSignal): Promise<CredentialRecord[]> => parseCredentials(await request('/providers/credentials', { signal }));
export const saveCredential = async (provider: string, kind: string, value: string): Promise<void> => {
  await request(`/providers/${encodeURIComponent(provider)}/credential`, { method: 'PUT', body: { kind, value } });
};
export const removeCredential = async (provider: string): Promise<void> => {
  await request(`/providers/${encodeURIComponent(provider)}/credential`, { method: 'DELETE' });
};
