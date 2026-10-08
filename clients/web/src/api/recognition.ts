import { request } from './client';
import { parseRecognitionStatus, type RecognitionStatus } from './types';

// The hub answers 401 both for a lost session and for "confirm your password again" (a wrong password, or a
// confirmation that has run out). Only the status read, which needs nothing but the session, may mean the former,
// so the calls below say a 401 is an ordinary refusal and the page re-reads the status to find out which it was.
const ROOT = '/owner-recognition';
const BENCH = `${ROOT}/benchmark`;
export type Kind = 'voice' | 'face';

export const getRecognition = async (signal?: AbortSignal): Promise<RecognitionStatus> => parseRecognitionStatus(await request(`${ROOT}/status`, { signal }));
export const reauthenticate = async (password: string): Promise<void> => {
  await request(`${ROOT}/reauth`, { method: 'POST', body: { password }, expectUnauthorized: true });
};
export const setBenchmark = async (enabled: boolean): Promise<void> => {
  await request(`${BENCH}/enabled`, { method: 'PUT', body: { enabled }, expectUnauthorized: true });
};
export const uploadSample = async (kind: Kind, blob: Blob): Promise<void> => {
  // The hub accepts exact media types, and a browser's recorder reports "audio/webm;codecs=opus"; send the bare type.
  const bare = new Blob([blob], { type: blob.type.split(';')[0]?.trim() || 'application/octet-stream' });
  await request(`${BENCH}/${kind}/samples`, { method: 'POST', body: bare, expectUnauthorized: true });
};
export const deleteSample = async (kind: Kind, id: string): Promise<void> => {
  await request(`${BENCH}/${kind}/samples/${encodeURIComponent(id)}`, { method: 'DELETE', expectUnauthorized: true });
};
export const deleteAllSamples = async (kind: Kind): Promise<void> => {
  await request(`${BENCH}/${kind}/samples`, { method: 'DELETE', expectUnauthorized: true });
};
export const exportSamples = async (kind: Kind): Promise<Blob> => request<Blob>(`${BENCH}/${kind}/export`, { asBlob: true, expectUnauthorized: true });
