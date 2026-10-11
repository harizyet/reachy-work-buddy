import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SAVE_DELAY_MS, SEARCH_DELAY_MS } from '../src/features/notes/useNotesEditor';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

const DAY = 86_400_000;
const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString();

function seeded() {
  return createFakeHub({
    status: SAMPLE_STATUS,
    notes: [
      { id: 'n1', title: '<img src=x onerror=boom()> Groceries', body: 'milk <b>eggs</b>\nbread', updated_at: ago(0) },
      { id: 'n2', title: 'Empty one', body: '', updated_at: ago(1) },
      { id: 'n3', title: 'Old idea', body: 'something', updated_at: ago(90) },
    ],
  });
}

// Fake timers drive the 700 ms autosave and 250 ms search debounce; userEvent needs to advance them.
function setup() {
  return userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTimeAsync(ms) });
}
const settle = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
const wait = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

beforeEach(() => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'], shouldAdvanceTime: true }));
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('Notes', () => {
  it('groups by date, previews literally, and opens a note into the editor', async () => {
    seeded();
    const { container } = renderApp('#/notes');
    const user = setup();
    await screen.findByText('Today');
    const sections = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(sections.slice(0, 2)).toEqual(['Today', 'Yesterday']);
    expect(sections[2]).toMatch(/^[A-Z][a-z]+( \d{4})?$/);
    const rows = screen.getAllByRole('button', { name: /Groceries|Empty one|Old idea/ });
    expect(rows[0]).toHaveTextContent('milk <b>eggs</b>');
    expect(rows[1]).toHaveTextContent('No additional text');
    expect(container.querySelector('img, b')).toBeNull();
    expect(screen.getByText('Select a note, or choose New note to start one.')).toBeInTheDocument();

    await user.click(rows[0]!);
    expect(screen.getByLabelText('Title')).toHaveValue('<img src=x onerror=boom()> Groceries');
    expect(screen.getByRole('textbox', { name: 'Note' })).toHaveValue('milk <b>eggs</b>\nbread');
    expect(container.querySelector('textarea b')).toBeNull();
  });

  it('autosaves an edit once after typing stops, as an update', async () => {
    const hub = seeded();
    renderApp('#/notes');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: /Groceries/ }));
    await user.type(screen.getByRole('textbox', { name: 'Note' }), '\nbutter');
    expect(hub.calls.some((c) => c.startsWith('PUT'))).toBe(false); // not before the pause
    await wait(SAVE_DELAY_MS + 50);
    await waitFor(() => expect(hub.calls.filter((c) => c === 'PUT /planner/notes/n1')).toHaveLength(1));
    expect(hub.bodies.find((b) => b.call === 'PUT /planner/notes/n1')?.body).toEqual({
      title: '<img src=x onerror=boom()> Groceries',
      body: 'milk <b>eggs</b>\nbread\nbutter',
      tag: null,
    });
    expect(await screen.findByText('Saved')).toBeInTheDocument();
  });

  it('creates once, then updates; Enter in the title moves to the body', async () => {
    const hub = seeded();
    renderApp('#/notes');
    const user = setup();
    await screen.findByText('Today');
    await user.click(screen.getByRole('button', { name: 'New note' }));
    await user.type(screen.getByLabelText('Title'), 'Trip plan{Enter}');
    expect(screen.getByRole('textbox', { name: 'Note' })).toHaveFocus();
    await user.type(screen.getByRole('textbox', { name: 'Note' }), 'book flights');
    await wait(SAVE_DELAY_MS + 50);
    await waitFor(() => expect(hub.calls).toContain('POST /planner/notes'));
    expect(hub.bodies.find((b) => b.call === 'POST /planner/notes')?.body).toEqual({ title: 'Trip plan', body: 'book flights', tag: null });
    await user.type(screen.getByRole('textbox', { name: 'Note' }), ' and hotel');
    await wait(SAVE_DELAY_MS + 50);
    await waitFor(() => expect(hub.calls.some((c) => c.startsWith('PUT /planner/notes/n'))).toBe(true));
    expect(hub.calls.filter((c) => c === 'POST /planner/notes')).toHaveLength(1);
  });

  it('never creates a blank note, and a note with no title takes its first line, then New Note', async () => {
    const hub = seeded();
    renderApp('#/notes');
    const user = setup();
    await screen.findByText('Today');
    await user.click(screen.getByRole('button', { name: 'New note' }));
    await wait(SAVE_DELAY_MS + 50);
    await user.click(screen.getByRole('button', { name: 'New note' })); // flushes the empty draft
    expect(hub.calls.some((c) => c.startsWith('POST'))).toBe(false);

    await user.type(screen.getByRole('textbox', { name: 'Note' }), '  first line here\nsecond');
    await wait(SAVE_DELAY_MS + 50);
    await waitFor(() => expect(hub.calls).toContain('POST /planner/notes'));
    expect((hub.bodies.find((b) => b.call === 'POST /planner/notes')?.body as { title: string }).title).toBe('first line here');
  });

  it('flushes a pending edit when another note is opened', async () => {
    const hub = seeded();
    renderApp('#/notes');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: /Empty one/ }));
    await user.type(screen.getByRole('textbox', { name: 'Note' }), 'quick');
    await user.click(screen.getByRole('button', { name: /Old idea/ })); // before the 700 ms elapse
    expect(hub.calls).toContain('PUT /planner/notes/n2');
    expect(screen.getByLabelText('Title')).toHaveValue('Old idea');
  });

  it('searches on the server after a short pause', async () => {
    const hub = seeded();
    renderApp('#/notes');
    const user = setup();
    await screen.findByText('Today');
    await user.type(screen.getByLabelText('Search all notes'), 'ages');
    await wait(SEARCH_DELAY_MS + 50);
    await waitFor(() => expect(hub.calls).toContain('GET /planner/notes?q=ages'));
    await user.clear(screen.getByLabelText('Search all notes'));
    await wait(SEARCH_DELAY_MS + 50);
    await waitFor(() => expect(hub.calls.filter((c) => c === 'GET /planner/notes').length).toBeGreaterThan(0));
    expect(hub.calls.filter((c) => c.includes('q=')).every((c) => c === 'GET /planner/notes?q=ages')).toBe(true);
  });

  it('asks before deleting; Cancel deletes nothing, Delete removes the note and closes the editor', async () => {
    const hub = seeded();
    renderApp('#/notes');
    const user = setup();
    expect(await screen.findByRole('button', { name: 'Delete note' })).toBeDisabled();
    await user.click(await screen.findByRole('button', { name: /Old idea/ }));
    await user.click(screen.getByRole('button', { name: 'Delete note' }));
    let dialog = within(await screen.findByRole('dialog', { hidden: true }));
    expect(dialog.getByText('“Old idea” will be deleted. This cannot be undone.')).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Cancel' }));
    expect(hub.calls.some((c) => c.startsWith('DELETE'))).toBe(false);
    await user.click(screen.getByRole('button', { name: 'Delete note' }));
    dialog = within(await screen.findByRole('dialog', { hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(hub.calls).toContain('DELETE /planner/notes/n3'));
    await waitFor(() => expect(screen.queryByRole('button', { name: /Old idea/ })).not.toBeInTheDocument());
    expect(screen.getByText('Select a note, or choose New note to start one.')).toBeInTheDocument();
  });

  it('reports a failed save without losing what was typed', async () => {
    const hub = seeded();
    renderApp('#/notes');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: /Empty one/ }));
    hub.respond((c) => c.startsWith('PUT'), () => jsonResponse({ detail: 'Companion core unavailable' }, 502));
    await user.type(screen.getByRole('textbox', { name: 'Note' }), 'important');
    await wait(SAVE_DELAY_MS + 50);
    expect(await screen.findByText('Not saved: Companion core unavailable')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Note' })).toHaveValue('important');
    hub.clearOverrides();
    await user.type(screen.getByRole('textbox', { name: 'Note' }), '!');
    await wait(SAVE_DELAY_MS + 50);
    expect(await screen.findByText('Saved')).toBeInTheDocument();
  });

  it('shows the empty state', async () => {
    createFakeHub({ status: SAMPLE_STATUS });
    renderApp('#/notes');
    expect(await screen.findByText('No notes.')).toBeInTheDocument();
    await settle();
  });
});

describe('Notes folders', () => {
  const filed = () =>
    createFakeHub({
      status: SAMPLE_STATUS,
      notes: [
        { id: 'a', title: 'Kickoff', body: 'agenda', updated_at: ago(0), tag: 'Meeting Notes' },
        { id: 'b', title: 'Budget', body: 'q4', updated_at: ago(1), tag: 'Projects/Project StarWars/Finance' },
        { id: 'c', title: 'Casting', body: 'leads', updated_at: ago(2), tag: 'Projects/Project StarWars' },
        { id: 'd', title: 'Loose', body: 'x', updated_at: ago(3), tag: null },
      ],
    });
  const nav = () => within(screen.getByRole('navigation', { name: 'Folders' }));

  it('shows the folder tree under All Notes with counts, and a folder holds the notes below it', async () => {
    filed();
    renderApp('#/notes');
    const user = setup();
    await screen.findByText('Kickoff');
    expect(nav().getByRole('button', { name: /^All Notes\s*4$/ })).toHaveAttribute('aria-current', 'true');
    expect(nav().getByRole('button', { name: /^Projects\s*2$/ })).toBeInTheDocument();
    expect(nav().getByRole('button', { name: /^Project StarWars\s*2$/ })).toBeInTheDocument();
    expect(nav().getByRole('button', { name: /^Finance\s*1$/ })).toBeInTheDocument();

    await user.click(nav().getByRole('button', { name: /^Projects/ }));
    expect(screen.getByRole('button', { name: /Budget/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Casting/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Kickoff/ })).toBeNull();
    expect(screen.getByRole('button', { name: /Budget/ })).toHaveTextContent('Projects › Project StarWars › Finance');

    await user.click(nav().getByRole('button', { name: /^Finance/ }));
    expect(screen.queryByRole('button', { name: /Casting/ })).toBeNull();
    await user.click(nav().getByRole('button', { name: /^All Notes/ }));
    expect(screen.getByRole('button', { name: /Loose/ })).toHaveTextContent('Notes');
  });

  it('files a note by its folder field once the field is left, normalised, and an unfiled note goes back with an empty one', async () => {
    const hub = filed();
    renderApp('#/notes');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: /Loose/ }));
    const field = screen.getByLabelText('Folder');
    expect(field).toHaveValue('');
    await user.type(field, 'All Notes/ Projects /Project StarWars/Legal');
    await wait(SAVE_DELAY_MS + 50);
    expect(hub.calls.some((c) => c.startsWith('PUT'))).toBe(false); // not while it is being typed
    await user.tab();
    await wait(SAVE_DELAY_MS + 50);
    await waitFor(() => expect(hub.bodies.find((b) => b.call === 'PUT /planner/notes/d')?.body).toMatchObject({ tag: 'Projects/Project StarWars/Legal' }));
    expect(await within(screen.getByRole('navigation', { name: 'Folders' })).findByRole('button', { name: /^Legal\s*1$/ })).toBeInTheDocument();

    await user.clear(field);
    await user.tab();
    await wait(SAVE_DELAY_MS + 50);
    await waitFor(() => expect(hub.bodies.filter((b) => b.call === 'PUT /planner/notes/d').at(-1)?.body).toMatchObject({ tag: null }));
  });

  it('refuses a folder that is too deep and does not save it', async () => {
    const hub = filed();
    renderApp('#/notes');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: /Loose/ }));
    await user.type(screen.getByLabelText('Folder'), 'a/b/c/d/e/f');
    await user.tab();
    await wait(SAVE_DELAY_MS + 50);
    expect(await screen.findByRole('alert')).toHaveTextContent('at most 5 levels');
    expect(hub.calls.some((c) => c.startsWith('PUT'))).toBe(false);
  });

  it('starts a new note in the folder being viewed', async () => {
    const hub = filed();
    renderApp('#/notes');
    const user = setup();
    await screen.findByText('Kickoff');
    await user.click(nav().getByRole('button', { name: /^Meeting Notes/ }));
    await user.click(screen.getByRole('button', { name: 'New note' }));
    expect(screen.getByLabelText('Folder')).toHaveValue('Meeting Notes');
    await user.type(screen.getByLabelText('Title'), 'Standup{Enter}');
    await wait(SAVE_DELAY_MS + 50);
    await waitFor(() => expect(hub.bodies.find((b) => b.call === 'POST /planner/notes')?.body).toMatchObject({ title: 'Standup', tag: 'Meeting Notes' }));
  });
});
