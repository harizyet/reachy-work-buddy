import { request } from './client';
import {
  parseLlmConfig,
  parsePersona,
  parseSearchLog,
  parseSession,
  parseWebSearchSettings,
  type LlmConfig,
  type Persona,
  type SearchLog,
  type SessionInfo,
  type WebSearchConfig,
} from './types';

export const getLlm = async (signal?: AbortSignal): Promise<LlmConfig> => parseLlmConfig(await request('/settings/llm', { signal }));
/** Body fields follow the hub: a provider is `null` to remove it, an `api_key` is sent only when changed (`null` removes the saved one). */
export const putLlm = async (config: unknown): Promise<LlmConfig> => parseLlmConfig(await request('/settings/llm', { method: 'PUT', body: config }));

export const getPersona = async (signal?: AbortSignal): Promise<Persona> => parsePersona(await request('/settings/persona', { signal }));
export const putPersona = async (persona: Omit<Persona, 'location'> & { location: string | null }): Promise<Persona> =>
  parsePersona(await request('/settings/persona', { method: 'PUT', body: persona }));

export const getWebSearch = async (signal?: AbortSignal): Promise<WebSearchConfig> => parseWebSearchSettings(await request('/settings/websearch', { signal }));
export const putWebSearch = async (patch: unknown): Promise<WebSearchConfig> =>
  parseWebSearchSettings(await request('/settings/websearch', { method: 'PUT', body: patch }));
export const getSearchLog = async (signal?: AbortSignal): Promise<SearchLog> => parseSearchLog(await request('/websearch/log', { signal }));

export const setSessionMode = async (user: string, mode: string): Promise<SessionInfo> =>
  parseSession(await request(`/sessions/${encodeURIComponent(user)}/mode`, { method: 'PATCH', body: { interaction_mode: mode } }));
export const setSessionDnd = async (user: string, dnd: boolean): Promise<SessionInfo> =>
  parseSession(await request(`/sessions/${encodeURIComponent(user)}/dnd`, { method: 'PATCH', body: { dnd } }));
