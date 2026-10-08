import { request } from './client';
import {
  parseAllowance,
  parseCodingEvents,
  parseCodingProjects,
  parseCodingSessions,
  parseTerminalSessions,
  parseUsageDimensions,
  type Allowance,
  type CodingEvent,
  type CodingProject,
  type CodingSession,
  type Dimension,
  type TerminalSession,
} from './types';

const ROOT = '/coding-agents';
const id = encodeURIComponent;

export const getAllowance = async (signal?: AbortSignal): Promise<Allowance> => parseAllowance(await request(`${ROOT}/allowance/claude-code`, { signal }));
export const listProjects = async (signal?: AbortSignal): Promise<CodingProject[]> => parseCodingProjects(await request(`${ROOT}/projects`, { signal }));
export const addProject = async (project: { name: string; repository_path: string; default_branch: string; provider: string }): Promise<void> => {
  await request(`${ROOT}/projects`, { method: 'POST', body: project });
};
export const listSessions = async (signal?: AbortSignal): Promise<CodingSession[]> => parseCodingSessions(await request(`${ROOT}/sessions`, { signal }));
export const startSession = async (session: { project_id: string; task_summary: string; branch: string | null }): Promise<void> => {
  await request(`${ROOT}/sessions`, { method: 'POST', body: session });
};
export const sessionEvents = async (sessionId: string): Promise<CodingEvent[]> => parseCodingEvents(await request(`${ROOT}/sessions/${id(sessionId)}/events`));
export const sessionUsage = async (sessionId: string): Promise<Dimension[]> => parseUsageDimensions(await request(`${ROOT}/sessions/${id(sessionId)}/usage`));
export const refreshSession = async (sessionId: string): Promise<void> => {
  await request(`${ROOT}/sessions/${id(sessionId)}/refresh`, { method: 'POST' });
};
export const stopSession = async (sessionId: string): Promise<void> => {
  await request(`${ROOT}/sessions/${id(sessionId)}/stop`, { method: 'POST' });
};
export const listTerminalSessions = async (signal?: AbortSignal): Promise<TerminalSession[]> =>
  parseTerminalSessions(await request(`${ROOT}/terminal-sessions`, { signal }));
