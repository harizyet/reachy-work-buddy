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
    expect(hub.bodies.find((b) => b.call === 'POST /planner/notes')?.body).toEqual({ title: 'Trip plan', body: 'book flights' });
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
