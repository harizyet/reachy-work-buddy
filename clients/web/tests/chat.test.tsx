import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse, type FakeChat } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

afterEach(() => vi.unstubAllGlobals());

// Cases from the legacy chat tab (clients/operator-ui/tests/{chat,chat_history,chat_citations}.test.cjs).
const status = { ...SAMPLE_STATUS, default_user_id: 'telegram-owner', owner_bound: false };
const box = () => screen.getByRole('textbox', { name: 'Message' });
const send = (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole('button', { name: 'Send' }));

function chatRecord(id: string, title: string, turns: FakeChat['turns'] = [], user = 'telegram-owner'): FakeChat {
  return { id, user_id: user, title, created_at: '2030-01-01T00:00:00Z', updated_at: '2030-01-02T00:00:00Z', turns };
}

describe('Chat', () => {
  it('sends a literal message in a new record, shows the reply and session, and refuses blank text', async () => {
    const hub = createFakeHub({ status });
    const { container } = renderApp('#/chat');
    const user = userEvent.setup();
    expect(await screen.findByText(/No session yet/)).toBeInTheDocument();
    await user.type(box(), '   ');
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled();
    await send(user);
    expect(hub.data.messages).toHaveLength(0);

    await user.clear(box());
    await user.type(box(), '<script>alert(1)</script>');
    await send(user);
    expect(await screen.findByText('Reply to: <script>alert(1)</script>')).toBeInTheDocument();
    expect(hub.data.messages[0]).toMatchObject({ user_id: 'telegram-owner', channel: 'web', text: '<script>alert(1)</script>', input_modality: 'text' });
    expect(hub.data.messages[0].chat_id).toBeTruthy();
    expect(hub.data.messages[0].force_frontier).toBeUndefined();
    expect(container.querySelector('#root script, article script')).toBeNull();
    expect(await screen.findByText(/office.*DND: on.*web/)).toBeInTheDocument();
    expect(hub.data.chats[0]!.title).toBe('<script>alert(1)</script>');
    expect(box()).toHaveValue('');
  });

  it('keeps Shift+Enter as a new line and Enter as send', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText(/No session yet/);
    await user.type(box(), 'First line{Shift>}{Enter}{/Shift}second');
    expect(box()).toHaveValue('First line\nsecond');
    expect(hub.data.messages).toHaveLength(0);
    await user.keyboard('{Enter}');
    await screen.findByText(/Reply to: First line/);
    expect(hub.data.messages[0].text).toBe('First line\nsecond');
  });

  it('shows web-search evidence: citations as links only for safe URLs, a Sources list, collapsed details, literal snippets', async () => {
    createFakeHub({
      status,
      reply: () => ({
        reply: 'Answer [S1] and [S2] and [S3].',
        web_search: {
          query: 'latest news',
          failed: false,
          results: [
            { title: 'Safe', url: 'https://example.com/source', snippet: '<script>snippet</script>', source_domain: 'example.com' },
            { title: 'Unsafe', url: 'javascript:alert(1)', snippet: 's', source_domain: 'evil' },
          ],
        },
      }),
    });
    const { container } = renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText(/No session yet/);
    await user.type(box(), 'Latest news{Enter}');
    const links = await screen.findAllByRole('link', { name: /\[S1\]/ });
    expect(links.length).toBeGreaterThanOrEqual(2); // in the text and in Sources
    for (const link of links) {
      expect(link).toHaveAttribute('href', 'https://example.com/source');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    }
    expect(screen.queryByRole('link', { name: /\[S2\]/ })).not.toBeInTheDocument(); // unsafe URL stays text
    expect(screen.queryByRole('link', { name: /\[S3\]/ })).not.toBeInTheDocument(); // unknown id stays text
    expect(container.querySelector('details')).not.toHaveAttribute('open');
    expect(screen.getByText('Web search · 2 results')).toBeInTheDocument();
    expect(screen.getByText('<script>snippet</script>')).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();
  });

  it('describes a failed or empty search, and attributes a meeting answer', async () => {
    let n = 0;
    createFakeHub({
      status,
      reply: () => {
        n += 1;
        return n === 1
          ? { reply: 'none', web_search: { query: 'q1', failed: false, results: [] } }
          : n === 2
            ? { reply: 'failed', web_search: { query: 'q2', failed: true, results: [] } }
            : { reply: 'from notes', context_meeting: 'Q3 planning' };
      },
    });
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText(/No session yet/);
    for (const text of ['one', 'two', 'three']) {
      await user.type(box(), `${text}{Enter}`);
      await screen.findByText(text === 'one' ? 'none' : text === 'two' ? 'failed' : 'from notes');
    }
    expect(screen.getByText('No results were found.')).toBeInTheDocument();
    expect(screen.getByText('The search failed. No results were available for this reply.')).toBeInTheDocument();
    expect(screen.getByText('From the meeting “Q3 planning”')).toBeInTheDocument();
  });

  it('on a failed send keeps the text, marks the message, and resets the frontier box; never resends by itself', async () => {
    const hub = createFakeHub({ status });
    hub.respond((c) => c === 'POST /messages', () => jsonResponse({ detail: 'down' }, 502));
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText(/No session yet/);
    await user.click(screen.getByRole('checkbox', { name: /frontier model/ }));
    await user.type(box(), 'Failed turn{Enter}');
    expect(await screen.findByText('Reply not received')).toBeInTheDocument();
    expect(screen.getByText('No reply received. This message may have been processed; check before sending it again.')).toBeInTheDocument();
    expect(box()).toHaveValue('Failed turn');
    expect(screen.getByRole('checkbox', { name: /frontier model/ })).not.toBeChecked();
    expect(hub.calls.filter((c) => c === 'POST /messages')).toHaveLength(1);
    hub.clearOverrides();
    await send(user);
    await screen.findByText('Reply to: Failed turn');
    expect(hub.data.messages.at(-1).force_frontier).toBeUndefined();
  });

  it('sends force_frontier once when ticked', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText(/No session yet/);
    await user.click(screen.getByRole('checkbox', { name: /frontier model/ }));
    await user.type(box(), 'Hard question{Enter}');
    await screen.findByText('Reply to: Hard question');
    expect(hub.data.messages[0].force_frontier).toBe(true);
    expect(screen.getByRole('checkbox', { name: /frontier model/ })).not.toBeChecked();
  });

  it('switching user clears the view and sends as the new user; Send is off until the id is applied', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText(/No session yet/);
    await user.type(box(), 'hello{Enter}');
    await screen.findByText('Reply to: hello');
    const id = screen.getByLabelText('User ID');
    await user.clear(id);
    await user.type(id, 'different-user');
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Use this user' }));
    expect(screen.queryByText('Reply to: hello')).not.toBeInTheDocument();
    expect(await screen.findByText(/User: different-user/)).toBeInTheDocument();
    await user.type(box(), 'as someone else{Enter}');
    await screen.findByText('Reply to: as someone else');
    expect(hub.data.messages.at(-1).user_id).toBe('different-user');
    expect(hub.data.sessions.size).toBe(2);
  });

  it('hides the user form when the hub is owner-bound', async () => {
    createFakeHub({ status: { ...status, owner_bound: true } });
    renderApp('#/chat');
    await screen.findByText(/No session yet/);
    expect(screen.queryByLabelText('User ID')).not.toBeInTheDocument();
  });

  it('autocompletes /reachy commands and runs a suggested command as a literal message', async () => {
    const hub = createFakeHub({
      status,
      reply: (text) => ({ reply: text.startsWith('/reachy') ? 'Done.' : 'You can say /reachy standby to put Reachy to sleep.' }),
    });
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText(/No session yet/);
    await user.type(box(), '/reachy sta');
    await user.click(screen.getByRole('button', { name: '/reachy standby' }));
    expect(box()).toHaveValue('/reachy standby');
    await send(user);
    await screen.findByText('Done.');
    expect(hub.data.messages.at(-1).text).toBe('/reachy standby');
    expect(screen.queryByRole('button', { name: /^Run:/ })).not.toBeInTheDocument();

    await user.type(box(), 'Could you put Reachy to sleep?{Enter}');
    await user.click(await screen.findByRole('button', { name: 'Run: /reachy standby' }));
    await waitFor(() => expect(hub.data.messages.filter((m) => m.text === '/reachy standby')).toHaveLength(2));
  });

  it('shows Telegram status', async () => {
    createFakeHub({ status: { ...status, telegram: { configured: true, healthy: false, last_poll_at: null, last_poll_error: 'HTTP 401' } } });
    renderApp('#/chat');
    expect(await screen.findByText('HTTP 401. You can continue the conversation here.')).toBeInTheDocument();
  });
});

describe('Chat history', () => {
  const seeded = () =>
    createFakeHub({
      status,
      chats: [
        chatRecord('c1', 'Newest chat', [
          { id: 't1', text: 'hi <b>there</b>', reply: 'hello', status: 'complete', web_search: null },
          { id: 't2', text: 'lost one', reply: null, status: 'unknown', web_search: null },
        ]),
        chatRecord('c2', 'Older chat', [{ id: 't3', text: 'old question', reply: 'old answer', status: 'complete', web_search: null }]),
        chatRecord('c3', "someone else's", [], 'other-user'),
      ],
    });

  it('opens the newest saved chat by itself, flags an unrecorded reply, and lists only this user’s chats', async () => {
    seeded();
    const { container } = renderApp('#/chat');
    expect(await screen.findByText('hi <b>there</b>')).toBeInTheDocument();
    expect(container.querySelector('article b')).toBeNull();
    expect(screen.getByText('hello')).toBeInTheDocument();
    expect(screen.getByText('Reply not recorded. This message may have been processed; check before sending again.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Newest chat' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Older chat/ })).toBeInTheDocument();
    expect(screen.queryByText("someone else's")).not.toBeInTheDocument();
  });

  it('opens another chat, searches titles, starts a new record, and continues the open one', async () => {
    const hub = seeded();
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText('hello');
    await user.click(screen.getByRole('button', { name: /^Older chat/ }));
    expect(await screen.findByText('old answer')).toBeInTheDocument();
    expect(screen.queryByText('hello')).not.toBeInTheDocument();
    await user.type(box(), 'another{Enter}');
    await screen.findByText('Reply to: another');
    expect(hub.data.messages.at(-1).chat_id).toBe('c2');

    await user.type(screen.getByLabelText('Find a chat'), 'zzz');
    expect(screen.getByText('No matching chats.')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Find a chat'));
    await user.click(screen.getByRole('button', { name: /New chat record/ }));
    expect(screen.getByRole('heading', { name: 'Chat with Reachy' })).toBeInTheDocument();
    expect(screen.queryByText('old answer')).not.toBeInTheDocument();
  });

  it('deletes a saved chat only after confirmation; deleting the open one empties the view', async () => {
    const hub = seeded();
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText('hello');
    await user.click(screen.getByRole('button', { name: 'Delete chat: Newest chat' }));
    let dialog = within(await screen.findByRole('dialog', { hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Cancel' }));
    expect(hub.calls.some((c) => c.startsWith('DELETE'))).toBe(false);
    await user.click(screen.getByRole('button', { name: 'Delete chat: Newest chat' }));
    dialog = within(await screen.findByRole('dialog', { hidden: true }));
    expect(dialog.getByText(/“Newest chat” and its saved messages will be removed/)).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(hub.calls).toContain('DELETE /chats/c1?user_id=telegram-owner'));
    await waitFor(() => expect(screen.queryByText('hello')).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /^Newest chat/ })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Chat with Reachy' })).toBeInTheDocument();
  });

  it('Hide messages clears the view without deleting anything', async () => {
    const hub = seeded();
    renderApp('#/chat');
    const user = userEvent.setup();
    await screen.findByText('hello');
    await user.click(screen.getByRole('button', { name: 'Hide messages' }));
    expect(screen.queryByText('hello')).not.toBeInTheDocument();
    expect(screen.getByText(/Messages hidden/)).toBeInTheDocument();
    expect(hub.calls.some((c) => c.startsWith('DELETE'))).toBe(false);
  });

  it('keeps the page usable when history cannot load', async () => {
    const hub = createFakeHub({ status });
    hub.respond((c) => c.startsWith('GET /chats?'), () => jsonResponse({ detail: 'Chat store unavailable' }, 500));
    renderApp('#/chat');
    expect(await screen.findByText(/Chat history unavailable: Chat store unavailable/)).toBeInTheDocument();
    expect(box()).toBeEnabled();
  });
});
