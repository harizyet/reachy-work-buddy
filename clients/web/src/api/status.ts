import { request } from './client';
import { parseStatus, type HubStatus } from './types';

export async function fetchStatus(signal?: AbortSignal): Promise<HubStatus> {
  return parseStatus(await request('/status', { signal }));
}
