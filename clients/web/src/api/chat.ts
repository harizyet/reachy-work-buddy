import { request } from './client';
import {
  parseChatDetail,
  parseChatRecord,
  parseChatRecords,
  parseMessageResult,
  parseSession,
  type ChatDetail,
  type ChatRecord,
  type MessageResult,
  type SessionInfo,
} from './types';

const q = encodeURIComponent;

export const listChats = async (user: string, signal?: AbortSignal): Promise<ChatRecord[]> =>
  parseChatRecords(await request(`/chats?user_id=${q(user)}`, { signal }));
export const getChat = async (id: string, user: string, signal?: AbortSignal): Promise<ChatDetail> =>
  parseChatDetail(await request(`/chats/${q(id)}?user_id=${q(user)}`, { signal }));
export const createChat = async (user: string, title: string, signal?: AbortSignal): Promise<ChatRecord> =>
  parseChatRecord(await request('/chats', { method: 'POST', body: { user_id: user, title }, signal }));
export const deleteChat = async (id: string, user: string): Promise<void> => {
  await request(`/chats/${q(id)}?user_id=${q(user)}`, { method: 'DELETE' });
};
export const getSession = async (user: string, signal?: AbortSignal): Promise<SessionInfo> =>
  parseSession(await request(`/sessions/${q(user)}`, { signal }));

export interface SendMessage {
  user_id: string;
  chat_id: string;
  text: string;
  context_meeting_id?: string;
  force_frontier?: boolean;
}
export const sendMessage = async (message: SendMessage, signal?: AbortSignal): Promise<MessageResult> =>
  parseMessageResult(await request('/messages', { method: 'POST', body: { channel: 'web', input_modality: 'text', ...message }, signal }));
