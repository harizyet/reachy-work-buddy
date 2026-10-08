import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { fetchMe } from '../../api/auth';
import { createChat, deleteChat, getChat, getSession, listChats, sendMessage } from '../../api/chat';
import { currentGeneration, StaleSessionError } from '../../api/client';
import type { ChatRecord, WebSearch } from '../../api/types';
import { useStatus } from '../overview/useStatus';

export interface ChatMessage {
  key: number;
  speaker: string;
  text: string;
  fromUser: boolean;
  note?: boolean;
  webSearch?: WebSearch | null;
  fromMeeting?: string | null;
  /** A short note under the message: "Reply not received" or "Reply not recorded…". */
  failure?: string;
}

export interface MeetingContext {
  id: string;
  title: string;
}

export const REQUEST_TIMEOUT_MS = 135_000;
export const NEW_CHAT_TITLE = 'Chat with Reachy';

// The chat lives above the router (inside the signed-in layout) so a request in flight, the open
// conversation and a meeting chosen as context survive moving between pages; signing out unmounts it.
function useChatController() {
  const queryClient = useQueryClient();
  const status = useStatus();
  const ownerBound = status.data?.ownerBound ?? false;
  const defaultUser = status.data?.defaultUserId ?? null;

  const [user, setUserState] = useState<string | null>(null);
  const [userInput, setUserInput] = useState('');
  const [activeChat, setActiveChat] = useState<string | null>(null);
  const [title, setTitle] = useState(NEW_CHAT_TITLE);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [frontier, setFrontier] = useState(false);
  const [pending, setPending] = useState(false);
  const [reading, setReading] = useState(false);
  const [notice, setNotice] = useState('');
  const [historyNotice, setHistoryNotice] = useState('');
  const [context, setContext] = useState<MeetingContext | null>(null);
  // History and session are only read once the Chat page has been opened, not at every sign-in.
  const [visited, setVisited] = useState(false);

  // Which user/conversation an answer belongs to. Anything that arrives for an older one is dropped.
  const epoch = useRef(0);
  const readVersion = useRef(0);
  const keys = useRef(0);
  const initialized = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const session = useRef(currentGeneration());
  const mounted = useRef(true);
  useEffect(() => () => {
    mounted.current = false;
    controller.current?.abort();
  }, []);

  const key = () => (keys.current += 1);
  const live = (version: number) => mounted.current && epoch.current === version && session.current === currentGeneration();

  const history = useQuery({
    queryKey: ['chat', 'history', user],
    queryFn: ({ signal }) => listChats(user as string, signal),
    enabled: user !== null && visited,
    refetchOnMount: 'always',
  });
  const sessionInfo = useQuery({
    queryKey: ['chat', 'session', user],
    queryFn: ({ signal }) => getSession(user as string, signal),
    enabled: user !== null && visited,
    retry: false,
  });

  const clearView = useCallback(() => {
    setMessages([]);
  }, []);

  const setUser = useCallback(
    (value: string): boolean => {
      const next = value.trim();
      if (pending || !next) return false;
      if (next !== user) {
        epoch.current += 1;
        readVersion.current += 1;
        initialized.current = false;
        setUserState(next);
        setActiveChat(null);
        setTitle(NEW_CHAT_TITLE);
        setMessages([]);
        setDraft('');
        setFrontier(false);
        setReading(false);
        setNotice('');
        setHistoryNotice('');
      }
      setUserInput(next);
      return true;
    },
    [pending, user],
  );

  // The owner-bound hub fixes the user to the owner's id; otherwise the first user is the hub's default.
  useEffect(() => {
    if (!user && defaultUser) setUser(defaultUser);
  }, [defaultUser, user, setUser]);

  const openChat = useCallback(
    async (id: string) => {
      if (pending || !user) return;
      const version = epoch.current;
      const read = (readVersion.current += 1);
      setReading(true);
      setHistoryNotice('Loading chat…');
      try {
        const record = await getChat(id, user);
        if (!live(version) || read !== readVersion.current) return;
        setActiveChat(record.id);
        setTitle(record.title);
        const out: ChatMessage[] = [];
        for (const turn of record.turns) {
          out.push({
            key: key(),
            speaker: 'You',
            text: turn.text,
            fromUser: true,
            failure: turn.status !== 'complete' ? 'Reply not recorded. This message may have been processed; check before sending again.' : undefined,
          });
          if (turn.reply !== null) out.push({ key: key(), speaker: 'Reachy', text: turn.reply, fromUser: false, webSearch: turn.web_search });
        }
        setMessages(out);
        setHistoryNotice('');
        setNotice('');
      } catch (error) {
        if (live(version) && read === readVersion.current && !(error instanceof StaleSessionError)) {
          setHistoryNotice(`Could not load chat: ${error instanceof Error ? error.message : 'unknown error'}`);
        }
      } finally {
        if (mounted.current && epoch.current === version && read === readVersion.current) setReading(false);
      }
    },
    [pending, user],
  );

  // The most recent saved chat opens by itself the first time a user's history loads.
  useEffect(() => {
    if (!history.data || initialized.current || pending || activeChat) return;
    initialized.current = true;
    const first = history.data[0];
    if (first) void openChat(first.id);
  }, [history.data, pending, activeChat, openChat]);

  const newChat = () => {
    if (pending || reading) return;
    initialized.current = true;
    setActiveChat(null);
    setTitle(NEW_CHAT_TITLE);
    clearView();
    setDraft('');
    setNotice('');
  };

  const remove = async (record: ChatRecord) => {
    if (pending || reading || !user) return;
    const version = epoch.current;
    try {
      await deleteChat(record.id, user);
      if (!live(version)) return;
      queryClient.setQueryData<ChatRecord[]>(['chat', 'history', user], (old) => old?.filter((r) => r.id !== record.id));
      if (activeChat === record.id) {
        setActiveChat(null);
        setTitle(NEW_CHAT_TITLE);
        clearView();
        setNotice('');
      }
      setHistoryNotice('');
    } catch (error) {
      if (live(version) && !(error instanceof StaleSessionError)) {
        setHistoryNotice(`Could not delete chat: ${error instanceof Error ? error.message : 'unknown error'}`);
      }
    }
  };

  const hideMessages = () => {
    clearView();
    setNotice('Messages hidden. Select the chat in history to show its saved messages again.');
  };

  const send = async (override?: string): Promise<void> => {
    const text = (override ?? draft).trim();
    if (!user || pending || reading || !text || userInput.trim() !== user) return;
    const version = epoch.current;
    const recipient = user;
    const forceFrontier = frontier;
    const meeting = context;
    setPending(true);
    const abort = new AbortController();
    controller.current = abort;
    // Do not retry an ambiguous failure automatically: a task or confirmation may already have been processed.
    const timeout = setTimeout(() => abort.abort(), REQUEST_TIMEOUT_MS);
    setNotice('Sending…');
    let sent = false;
    let sentKey: number | null = null;
    let chatId = activeChat;
    try {
      await fetchMe(abort.signal);
      if (!live(version)) return;
      if (!chatId) {
        const record = await createChat(recipient, text.slice(0, 120), abort.signal);
        if (!live(version)) return;
        chatId = record.id;
        setActiveChat(record.id);
        setTitle(record.title);
        initialized.current = true;
      }
      sentKey = key();
      setMessages((m) => [...m, { key: sentKey as number, speaker: 'You', text, fromUser: true }]);
      setDraft('');
      setFrontier(false);
      sent = true;
      const result = await sendMessage(
        {
          user_id: recipient,
          chat_id: chatId,
          text,
          ...(meeting ? { context_meeting_id: meeting.id } : {}),
          ...(forceFrontier ? { force_frontier: true } : {}),
        },
        abort.signal,
      );
      if (!live(version)) return;
      setMessages((m) => [...m, { key: key(), speaker: 'Reachy', text: result.reply, fromUser: false, webSearch: result.web_search, fromMeeting: result.context_meeting }]);
      setNotice('');
      void queryClient.invalidateQueries({ queryKey: ['chat', 'session', recipient] });
    } catch (error) {
      if (!live(version) || error instanceof StaleSessionError) return;
      if (sentKey !== null) {
        const failed = sentKey;
        setMessages((m) => m.map((x) => (x.key === failed ? { ...x, failure: 'Reply not received' } : x)));
      }
      setNotice(
        sent
          ? 'No reply received. This message may have been processed; check before sending it again.'
          : 'Could not prepare this chat. Your message was not sent.',
      );
      setDraft((current) => current || text);
    } finally {
      clearTimeout(timeout);
      if (mounted.current && epoch.current === version) {
        setPending(false);
        controller.current = null;
        void queryClient.invalidateQueries({ queryKey: ['chat', 'history', recipient] });
      }
    }
  };

  // A robot microphone turn shares this transcript, so spoken and typed turns read as one conversation.
  const appendVoiceTurn = useCallback((turn: { transcript?: string; outcome: string; reply?: string; reason?: string; web_search?: WebSearch | null }) => {
    const add = (m: Omit<ChatMessage, 'key'>) => setMessages((all) => [...all, { ...m, key: key() }]);
    if (turn.transcript) add({ speaker: 'You · spoken to Reachy', text: turn.transcript, fromUser: true });
    if (turn.outcome === 'spoken') add({ speaker: 'Reachy · said aloud', text: turn.reply ?? '', fromUser: false, webSearch: turn.web_search });
    else if (turn.outcome === 'withheld')
      add({ speaker: `Reachy · not spoken (${turn.reason || 'withheld'})`, text: turn.reply ?? '', fromUser: false, webSearch: turn.web_search });
    else if (turn.outcome === 'no_speech') add({ speaker: 'Reachy', text: 'I heard a sound but no words. Try again.', fromUser: false, note: true });
    else if (turn.outcome === 'failed')
      add({ speaker: 'Reachy', text: `That turn failed: ${turn.reason || 'unknown error'}. Speak again when listening resumes.`, fromUser: false, note: true });
    else if (turn.outcome === 'cancelled') {
      const why = turn.reason && turn.reason !== 'Stopped' ? `Not answered: ${turn.reason}.` : 'Stopped before replying.';
      add({ speaker: 'Reachy', text: why, fromUser: false, note: true });
    }
  }, []);

  return {
    ownerBound,
    telegram: status.data?.telegram ?? null,
    telegramKnown: !status.isPending && !status.error,
    user,
    userInput,
    setUserInput,
    setUser,
    activeChat,
    title,
    messages,
    draft,
    setDraft,
    frontier,
    setFrontier,
    pending,
    reading,
    notice,
    historyNotice,
    history: history.data ?? [],
    historyError: history.error && !(history.error instanceof StaleSessionError) ? history.error.message : '',
    session: sessionInfo,
    context,
    setContext,
    clearContext: () => setContext(null),
    openChat,
    newChat,
    remove,
    hideMessages,
    send,
    appendVoiceTurn,
    markVisited: () => setVisited(true),
    chooseUser: (value: string) => {
      if (!setUser(value)) setNotice('Enter a user ID before sending.');
    },
  };
}

export type ChatController = ReturnType<typeof useChatController>;

const ChatContext = createContext<ChatController | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  return <ChatContext.Provider value={useChatController()}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatController {
  const value = useContext(ChatContext);
  if (!value) throw new Error('useChat needs a ChatProvider');
  return value;
}
