import { request } from './client';
import { parseAudit, parseNotifications, parseStatus, type HubStatus } from './types';

export async function fetchStatus(signal?: AbortSignal): Promise<HubStatus> {
  return parseStatus(await request('/status', { signal }));
}

export const fetchAudit = async (user: string, signal?: AbortSignal) => parseAudit(await request(`/audit/${encodeURIComponent(user)}?limit=10`, { signal }));
export const fetchNotifications = async (user: string, signal?: AbortSignal) => parseNotifications(await request(`/notifications/${encodeURIComponent(user)}`, { signal }));
