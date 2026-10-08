import { request } from './client';
import { parseMotion, parseRobotRefs, parseVoiceOverview, parseVoiceSession, type MotionSettings, type RobotRef, type VoiceOverview, type VoiceSession } from './types';

const id = encodeURIComponent;

export const getVoiceOverview = async (signal?: AbortSignal): Promise<VoiceOverview> => parseVoiceOverview(await request('/robot-voice', { signal }));
export const startVoice = async (robotId: string, userId: string | null): Promise<VoiceSession> =>
  parseVoiceSession(await request('/robot-voice/start', { method: 'POST', body: { robot_id: robotId, user_id: userId } }));
export const renewVoice = async (sessionId: string): Promise<VoiceSession> =>
  parseVoiceSession(await request('/robot-voice/renew', { method: 'POST', body: { voice_session_id: sessionId } }));
export const stopVoice = async (sessionId: string): Promise<VoiceSession> =>
  parseVoiceSession(await request('/robot-voice/stop', { method: 'POST', body: { voice_session_id: sessionId } }));
export const setWakeArmed = async (robotId: string, armed: boolean, userId: string | null): Promise<VoiceOverview> =>
  parseVoiceOverview(await request('/robot-voice/wake', { method: 'POST', body: { robot_id: robotId, armed, user_id: userId } }));

export const listRobots = async (signal?: AbortSignal): Promise<RobotRef[]> => parseRobotRefs(await request('/robots', { signal }));
export const getMotion = async (robotId: string, signal?: AbortSignal): Promise<MotionSettings> =>
  parseMotion(await request(`/robots/${id(robotId)}/settings/motion`, { signal }));
export const putMotion = async (robotId: string, settings: { conversation_motion: boolean; speech_wobble: boolean }): Promise<MotionSettings> =>
  parseMotion(await request(`/robots/${id(robotId)}/settings/motion`, { method: 'PUT', body: settings }));
