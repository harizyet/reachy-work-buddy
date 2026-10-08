import { hubBase, request } from './client';
import {
  parseDeepInfo,
  parseDeepJob,
  parseMeeting,
  parseMeetings,
  parseSuggestionResult,
  type DeepInfo,
  type DeepJob,
  type Meeting,
  type SuggestionResult,
} from './types';

const id = encodeURIComponent;

export const listMeetings = async (signal?: AbortSignal): Promise<Meeting[]> => parseMeetings(await request('/meetings', { signal }));
export const getMeeting = async (meetingId: string, signal?: AbortSignal): Promise<Meeting> =>
  parseMeeting(await request(`/meetings/${id(meetingId)}`, { signal }));
export const uploadMeeting = async (form: FormData): Promise<Meeting> => parseMeeting(await request('/meetings', { method: 'POST', body: form }));
export const deleteMeeting = async (meetingId: string): Promise<void> => {
  await request(`/meetings/${id(meetingId)}`, { method: 'DELETE' });
};
export const cancelMeeting = async (meetingId: string): Promise<Meeting> =>
  parseMeeting(await request(`/meetings/${id(meetingId)}/cancel`, { method: 'POST' }));
export const renameSpeaker = async (meetingId: string, label: string, name: string): Promise<Meeting> =>
  parseMeeting(await request(`/meetings/${id(meetingId)}/speakers`, { method: 'PUT', body: { names: { [label]: name } } }));
export const setTitle = async (meetingId: string, title: string, description: string): Promise<Meeting> =>
  parseMeeting(await request(`/meetings/${id(meetingId)}/title`, { method: 'PUT', body: { title, description } }));
export const describeMeeting = async (meetingId: string): Promise<Meeting> =>
  parseMeeting(await request(`/meetings/${id(meetingId)}/describe`, { method: 'POST', body: { model: 'local' } }));
export const correctLine = async (meetingId: string, index: number, text: string): Promise<Meeting> =>
  parseMeeting(await request(`/meetings/${id(meetingId)}/corrections/${index}`, { method: 'PUT', body: { text } }));
export const revertLine = async (meetingId: string, index: number): Promise<Meeting> =>
  parseMeeting(await request(`/meetings/${id(meetingId)}/corrections/${index}`, { method: 'DELETE' }));
export const replaceText = async (meetingId: string, find: string, replace: string): Promise<{ replaced_segments: number }> => {
  const result = (await request(`/meetings/${id(meetingId)}/corrections/replace`, { method: 'POST', body: { find, replace } })) as { replaced_segments?: unknown };
  return { replaced_segments: typeof result.replaced_segments === 'number' ? result.replaced_segments : 0 };
};
export const suggestCorrections = async (meetingId: string, model: string): Promise<SuggestionResult> =>
  parseSuggestionResult(await request(`/meetings/${id(meetingId)}/corrections/suggest`, { method: 'POST', body: { model } }));
export const writeOutput = async (meetingId: string, kind: 'summary' | 'minutes', model: string): Promise<Meeting> =>
  parseMeeting(await request(`/meetings/${id(meetingId)}/outputs/${kind}`, { method: 'POST', body: { model } }));
export const clearOutput = async (meetingId: string, kind: 'summary' | 'minutes'): Promise<Meeting> =>
  parseMeeting(await request(`/meetings/${id(meetingId)}/outputs/${kind}`, { method: 'DELETE' }));

export const deepInfo = async (): Promise<DeepInfo> => parseDeepInfo(await request('/deep-review/info'));
export const currentDeepJob = async (signal?: AbortSignal): Promise<DeepJob | null> => {
  const job = await request('/deep-review/current', { signal });
  return job == null ? null : parseDeepJob(job);
};
export const getDeepJob = async (jobId: string, signal?: AbortSignal): Promise<DeepJob> => parseDeepJob(await request(`/deep-review/${id(jobId)}`, { signal }));
export const startDeepReview = async (meetingId: string, task: 'corrections' | 'summary' | 'minutes'): Promise<DeepJob> =>
  parseDeepJob(
    await request(task === 'corrections' ? `/meetings/${id(meetingId)}/corrections/deep-review` : `/meetings/${id(meetingId)}/outputs/${task}/deep`, { method: 'POST' }),
  );

/** The recording streams from the hub behind the owner cookie; a relative URL keeps it correct under /hub/. */
export const meetingAudioUrl = (meetingId: string) => `${hubBase()}/meetings/${id(meetingId)}/audio`;
