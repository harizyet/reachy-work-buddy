import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import type { TelegramHealth } from '../../api/types';
import { SearchDetails, SourcesList, withCitations } from './citations';
import { useChat, type ChatMessage } from './ChatProvider';

// The fixed set of explicit commands the parser accepts: used only for autocomplete and buttons here, never to decide
// anything (that is companion_core/commands/parser.py).
export const REACHY_COMMANDS = ['/reachy standby', '/reachy wake', '/reachy status'];
const SUGGESTED_COMMAND = /\/reachy (standby|wake|status)\b/;

export function telegramLabel(t: TelegramHealth): string {
  if (!t.configured) return 'Not configured';
  if (t.last_poll_error) return t.last_poll_error;
  if (t.healthy) return 'Polling healthy';
  return t.last_poll_at ? 'Polling stalled' : 'Awaiting first successful poll';
}

function telegramLine(t: TelegramHealth | null, known: boolean): string {
  if (!t) return known ? 'Checking Telegram…' : 'Telegram status unavailable. You can still try web chat.';
  if (!t.configured) return 'Telegram is not configured. You can chat here.';
  if (t.healthy) return 'Telegram polling is healthy. You can also chat here anytime.';
  return `${telegramLabel(t)}. You can continue the conversation here.`;
}

export function ChatPage() {
  const chat = useChat();
  const [deleting, setDeleting] = useState<{ id: string; title: string } | null>(null);
  const [historySearch, setHistorySearch] = useState('');
  const textRef = useRef<HTMLTextAreaElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const busy = chat.pending || chat.reading;

  useEffect(() => chat.markVisited(), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    logRef.current?.lastElementChild?.scrollIntoView?.({ block: 'nearest' });
  }, [chat.messages.length]);
  useEffect(() => {
    if (!chat.pending) textRef.current?.focus();
  }, [chat.pending]);

  const matches = chat.history.filter((r) => r.title.toLowerCase().includes(historySearch.trim().toLowerCase()));
  const hints = chat.draft.startsWith('/') ? REACHY_COMMANDS.filter((c) => c.startsWith(chat.draft)) : [];
  const session = chat.session.data
    ? `User: ${chat.user} · Mode: ${chat.session.data.interaction_mode} · DND: ${chat.session.data.dnd ? 'on' : 'off'} · Active channel: ${chat.session.data.active_channel}`
    : chat.session.error
      ? 'status' in chat.session.error && (chat.session.error as { status?: number }).status === 404
        ? `User: ${chat.user} · No session yet. Your first message will start one.`
        : `User: ${chat.user} · Session status unavailable.`
      : chat.user
        ? `User: ${chat.user} · Loading session…`
        : 'Loading session…';

  function submit(event: FormEvent) {
    event.preventDefault();
    void chat.send();
  }

  return (
    <div className="grid gap-4 md:grid-cols-[16rem_1fr]">
      <aside aria-label="Chat history" className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
        <Button className="w-full" onClick={chat.newChat} disabled={busy || !chat.user}>
          ＋ New chat record
        </Button>
        <h2 className="mt-3 font-semibold">Previous chats</h2>
        <label className="mt-1 block text-sm">
          Find a chat
          <input
            type="search"
            placeholder="Search titles…"
            className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2"
            value={historySearch}
            onChange={(e) => setHistorySearch(e.target.value)}
          />
        </label>
        <p role="status" className="min-h-5 text-sm text-[var(--bad)]">
          {chat.historyNotice || (chat.historyError ? `Chat history unavailable: ${chat.historyError}` : '')}
        </p>
        <ul className="divide-y divide-[var(--border)]">
          {matches.map((record) => (
            <li key={record.id} className="flex items-center gap-1 py-1">
              <button
                type="button"
                aria-pressed={record.id === chat.activeChat}
                disabled={busy}
                className={`min-w-0 flex-1 rounded px-2 py-1 text-left text-sm ${record.id === chat.activeChat ? 'bg-[var(--hover)]' : ''}`}
                onClick={() => void chat.openChat(record.id)}
              >
                <span className="block break-words">{record.title}</span>
                <small className="text-[var(--muted)]">{new Date(record.updated_at).toLocaleDateString()}</small>
              </button>
              <button
                type="button"
                aria-label={`Delete chat: ${record.title}`}
                disabled={busy}
                className="rounded px-2 text-[var(--muted)] hover:bg-[var(--hover)]"
                onClick={() => setDeleting({ id: record.id, title: record.title })}
              >
                ✕
              </button>
            </li>
          ))}
          {matches.length === 0 && (
            <li className="py-2 text-sm text-[var(--muted)]">{historySearch.trim() ? 'No matching chats.' : 'Your chats will appear here.'}</li>
          )}
        </ul>
        <p className="mt-3 text-xs text-[var(--muted)]">
          Typed web messages are saved on your homelab. Chat records share your assistant’s context across channels.
        </p>
      </aside>

      <section className="flex min-w-0 flex-col rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4" aria-labelledby="chat-title">
        <div className="mb-2 flex items-start justify-between gap-2">
          <div>
            <span className="block text-[0.7rem] font-medium tracking-widest text-[var(--muted)]">YOUR COMPANION</span>
            <h1 id="chat-title" className="text-xl font-semibold">{chat.title}</h1>
          </div>
          <Button variant="secondary" onClick={chat.hideMessages} disabled={chat.pending}>
            Hide messages
          </Button>
        </div>
        {!chat.ownerBound && (
          <form
            className="mb-2 flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              chat.chooseUser(chat.userInput);
            }}
          >
            <label className="flex-1 text-sm">
              User ID
              <input
                className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2"
                required
                autoComplete="off"
                placeholder="Loading default user…"
                value={chat.userInput}
                disabled={chat.pending}
                onChange={(e) => chat.setUserInput(e.target.value)}
              />
            </label>
            <Button variant="secondary" type="submit" disabled={chat.pending}>
              Use this user
            </Button>
          </form>
        )}
        <p role="status" className="text-sm">{session}</p>
        <p role="status" className={`text-sm ${chat.telegram?.configured && !chat.telegram.healthy ? 'text-[var(--warn)]' : 'text-[var(--muted)]'}`}>
          {telegramLine(chat.telegram, chat.telegramKnown)}
        </p>
        <p className="text-sm text-[var(--muted)]">
          Select a saved chat or start a new record. Live robot voice turns appear here but are not saved in chat history.
        </p>

        <div
          ref={logRef}
          role="log"
          aria-label="Conversation"
          aria-live="polite"
          className="my-3 flex max-h-[28rem] min-h-40 flex-col gap-3 overflow-y-auto rounded border border-[var(--border)] p-3"
        >
          {chat.messages.length === 0 && <p className="text-sm text-[var(--muted)]">Send a message to start or continue your conversation.</p>}
          {chat.messages.map((m) => (
            <Message key={m.key} message={m} onRun={(command) => void chat.send(command)} disabled={chat.pending} />
          ))}
        </div>

        <form onSubmit={submit}>
          <label className="block text-sm">
            Message
            <textarea
              ref={textRef}
              rows={3}
              required
              disabled={chat.reading || !chat.user}
              placeholder="Ask Reachy something… (try /reachy standby)"
              className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2"
              value={chat.draft}
              onChange={(e) => chat.setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  if (!chat.pending) void chat.send();
                }
              }}
            />
          </label>
          {chat.context && (
            <div className="my-2 rounded border border-[var(--border)] p-2 text-sm">
              <span>
                Meeting context: <strong>{chat.context.title}</strong>
              </span>{' '}
              <button type="button" aria-label="Stop using this meeting as context" className="px-1" onClick={chat.clearContext}>
                ✕
              </button>
              <small className="block text-[var(--muted)]">
                Questions are answered from this meeting with the local model; the transcript stays on your homelab. For a stronger answer, tick "Use frontier model" below: it sends this meeting's text to your cloud provider.
              </small>
            </div>
          )}
          {hints.length > 0 && hints[0] !== chat.draft && (
            <div className="my-1 flex flex-wrap gap-1">
              {hints.map((c) => (
                <button key={c} type="button" className="rounded border border-[var(--border)] px-2 py-1 text-sm" onClick={() => { chat.setDraft(c); textRef.current?.focus(); }}>
                  {c}
                </button>
              ))}
            </div>
          )}
          <label className="my-2 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={chat.frontier} disabled={chat.pending} onChange={(e) => chat.setFrontier(e.target.checked)} />
            Use frontier model for this message (sends conversation context to cloud)
          </label>
          <div className="flex items-center justify-between gap-2">
            <span role="status" className="text-sm text-[var(--muted)]">{chat.notice}</span>
            <Button type="submit" disabled={busy || !chat.user || chat.userInput.trim() !== chat.user}>
              Send
            </Button>
          </div>
        </form>
      </section>

      <Dialog open={deleting !== null} title="Delete this chat?" onClose={() => setDeleting(null)}>
        <h2 className="text-lg font-semibold">Delete this chat?</h2>
        <p className="my-3 break-words text-sm">
          {`“${deleting?.title ?? ''}” and its saved messages will be removed from your chat history. This cannot be undone.`}
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
          <Button
            onClick={() => {
              const target = chat.history.find((r) => r.id === deleting?.id);
              setDeleting(null);
              if (target) void chat.remove(target);
            }}
          >
            Delete
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

function Message({ message, onRun, disabled }: { message: ChatMessage; onRun: (command: string) => void; disabled: boolean }) {
  const cited = !message.fromUser && message.webSearch && message.webSearch.results.length > 0;
  const command = !message.fromUser ? SUGGESTED_COMMAND.exec(message.text) : null;
  return (
    <article className={`max-w-[85%] rounded-lg p-2 ${message.fromUser ? 'self-end bg-[var(--hover)]' : 'self-start border border-[var(--border)]'} ${message.note ? 'italic' : ''}`}>
      <strong className="block text-xs text-[var(--muted)]">{message.speaker}</strong>
      <p className="whitespace-pre-wrap break-words">{cited ? withCitations(message.text, message.webSearch!.results) : message.text}</p>
      {cited && <SourcesList results={message.webSearch!.results} />}
      {!message.fromUser && message.webSearch && <SearchDetails search={message.webSearch} />}
      {!message.fromUser && message.fromMeeting && <small className="block text-[var(--muted)]">{`From the meeting “${message.fromMeeting}”`}</small>}
      {command && (
        <button
          type="button"
          disabled={disabled}
          className="mt-1 rounded border border-[var(--accent)] px-2 py-1 text-sm text-[var(--accent)]"
          onClick={() => onRun(command[0])}
        >
          {`Run: ${command[0]}`}
        </button>
      )}
      {message.failure && <small className="block">{message.failure}</small>}
    </article>
  );
}
