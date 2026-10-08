import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

afterEach(() => vi.unstubAllGlobals());

const DAY = 86_400_000;
function at(days: number, hour: number, minute = 0): string {
  const d = new Date(Date.now() + days * DAY);
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
}

// Characterised against the legacy tabs (clients/operator-ui/tests/planner.test.cjs) and the
// real hub (services/reachy-hub/tests/test_web_client.py::test_planner_*).
function seeded() {
  return createFakeHub({
    status: SAMPLE_STATUS,
    tasks: [
      { id: 't1', text: '<b>Sweep</b> garage', status: 'open' },
      { id: 't2', text: 'Plan menu', status: 'open' },
      { id: 't3', text: 'Old chore', status: 'done' },
    ],
    reminders: [
      { id: 'r1', text: 'Send <i>recipe</i>', due_at: at(1, 16), status: 'pending' },
      { id: 'r2', text: 'Missed call', due_at: at(-1, 9, 30), status: 'pending' },
      { id: 'r3', text: 'Book club', due_at: at(-3, 18), status: 'done' },
    ],
  });
}

describe('To Do', () => {
  it('lists open tasks literally, with the completed section collapsed', async () => {
    seeded();
    const { container } = renderApp('#/todo');
    expect(await screen.findByRole('heading', { name: 'To Do' })).toBeInTheDocument();
    expect(await screen.findByText('<b>Sweep</b> garage')).toBeInTheDocument();
    expect(container.querySelector('b')).toBeNull();
    expect(screen.getByText('Plan menu')).toBeInTheDocument();
    expect(screen.queryByText('Old chore')).not.toBeInTheDocument();
    const toggle = screen.getByRole('button', { name: '1 Completed · Show' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await userEvent.setup().click(toggle);
    expect(screen.getByRole('button', { name: '1 Completed · Hide' })).toBeInTheDocument();
    expect(screen.getByText('Old chore')).toBeInTheDocument();
  });

  it('completes, reopens, renames, adds and deletes through the hub and reloads the list', async () => {
    const hub = seeded();
    renderApp('#/todo');
    const user = userEvent.setup();
    await screen.findByText('Plan menu');

    await user.click(screen.getByRole('checkbox', { name: 'Complete: Plan menu' }));
    await waitFor(() => expect(hub.calls).toContain('POST /planner/tasks/t2/complete'));
    await waitFor(() => expect(screen.queryByText('Plan menu')).not.toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: '2 Completed · Show' }));
    await user.click(screen.getByRole('checkbox', { name: 'Reopen: Old chore' }));
    await waitFor(() => expect(hub.calls).toContain('POST /planner/tasks/t3/reopen'));
    expect(await screen.findByRole('button', { name: 'Edit: Old chore' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Edit: Old chore' }));
    const edit = screen.getByRole('textbox', { name: 'Edit to-do' });
    await user.clear(edit);
    await user.type(edit, 'Old chore, renamed{Enter}');
    await waitFor(() => expect(hub.calls).toContain('PUT /planner/tasks/t3'));
    expect(hub.bodies.find((b) => b.call === 'PUT /planner/tasks/t3')?.body).toEqual({ text: 'Old chore, renamed' });
    expect(await screen.findByText('Old chore, renamed')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Delete: <b>Sweep</b> garage' }));
    await waitFor(() => expect(hub.calls).toContain('DELETE /planner/tasks/t1'));
    await waitFor(() => expect(screen.queryByText('<b>Sweep</b> garage')).not.toBeInTheDocument());
  });

  it('adds with an inline row that stays open for the next item, and Escape closes it', async () => {
    const hub = seeded();
    renderApp('#/todo');
    const user = userEvent.setup();
    await screen.findByText('Plan menu');
    await user.click(screen.getByRole('button', { name: /New Reminder/ }));
    const row = screen.getByRole('textbox', { name: 'New to-do' });
    await user.type(row, 'Water plants{Enter}');
    await waitFor(() => expect(hub.calls).toContain('POST /planner/tasks'));
    expect(hub.bodies.find((b) => b.call === 'POST /planner/tasks')?.body).toEqual({ text: 'Water plants' });
    expect(await screen.findByText('Water plants')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'New to-do' })).toHaveValue('');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('textbox', { name: 'New to-do' })).not.toBeInTheDocument();
  });

  it('does not create a blank task, nor rename to blank or unchanged text', async () => {
    const hub = seeded();
    renderApp('#/todo');
    const user = userEvent.setup();
    await screen.findByText('Plan menu');
    await user.click(screen.getByRole('button', { name: /New Reminder/ }));
    await user.type(screen.getByRole('textbox', { name: 'New to-do' }), '   {Enter}');
    expect(screen.queryByRole('textbox', { name: 'New to-do' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Edit: Plan menu' }));
    await user.type(screen.getByRole('textbox', { name: 'Edit to-do' }), '{Enter}'); // unchanged
    await user.click(screen.getByRole('button', { name: 'Edit: Plan menu' }));
    await user.clear(screen.getByRole('textbox', { name: 'Edit to-do' }));
    await user.keyboard('{Enter}'); // blank
    expect(hub.calls.filter((c) => c.startsWith('POST /planner/tasks') || c.startsWith('PUT'))).toEqual([]);
  });

  it('shows the hub error and still reloads when a change fails', async () => {
    const hub = seeded();
    renderApp('#/todo');
    const user = userEvent.setup();
    await screen.findByText('Plan menu');
    hub.data.tasks = hub.data.tasks.filter((t) => t.id !== 't2'); // deleted elsewhere
    await user.click(screen.getByRole('checkbox', { name: 'Complete: Plan menu' }));
    expect(await screen.findByText("no task 't2'")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('Plan menu')).not.toBeInTheDocument());
  });

  it('shows an empty state, and a load error with a working retry', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    hub.respond((c) => c === 'GET /planner/tasks', () => jsonResponse({ detail: 'Companion core unavailable' }, 502));
    renderApp('#/todo');
    expect(await screen.findByRole('alert')).toHaveTextContent('Companion core unavailable');
    hub.clearOverrides();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Nothing to do yet.')).toBeInTheDocument();
  });
});

describe('Reminders', () => {
  it('orders by due date, marks overdue, and keeps completed ones ticked and disabled', async () => {
    seeded();
    const { container } = renderApp('#/reminders');
    await screen.findByText('Missed call');
    const items = within(screen.getAllByRole('list')[0]!).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Missed call');
    expect(items[0]).toHaveTextContent(/Yesterday, 9:30\s?AM · due/);
    expect(items[1]).toHaveTextContent(/Tomorrow, 4:00\s?PM/);
    expect(items[1]).not.toHaveTextContent('· due');
    expect(screen.getByText('Send <i>recipe</i>')).toBeInTheDocument();
    expect(container.querySelector('i')).toBeNull();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '1 Completed · Show' }));
    expect(screen.getByRole('checkbox', { name: 'Completed: Book club' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Completed: Book club' })).toBeChecked();
  });

  it('completes and deletes reminders through the hub', async () => {
    const hub = seeded();
    renderApp('#/reminders');
    const user = userEvent.setup();
    await screen.findByText('Missed call');
    await user.click(screen.getByRole('checkbox', { name: 'Complete: Missed call' }));
    await waitFor(() => expect(hub.calls).toContain('POST /planner/reminders/r2/complete'));
    await waitFor(() => expect(screen.getByRole('button', { name: '2 Completed · Show' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Delete: Send <i>recipe</i>' }));
    await waitFor(() => expect(hub.calls).toContain('DELETE /planner/reminders/r1'));
  });

  it('creates a reminder from the sheet with the local date and time as an instant', async () => {
    const hub = seeded();
    renderApp('#/reminders');
    const user = userEvent.setup();
    await screen.findByText('Missed call');
    await user.click(screen.getByRole('button', { name: /New Reminder/ }));
    const sheet = await screen.findByRole('dialog', { name: 'New Reminder', hidden: true });
    const inSheet = within(sheet);
    await user.type(inSheet.getByLabelText('Title'), 'Call Lisa');
    await user.clear(inSheet.getByLabelText('Date'));
    await user.type(inSheet.getByLabelText('Date'), '2030-03-04');
    await user.clear(inSheet.getByLabelText('Time'));
    await user.type(inSheet.getByLabelText('Time'), '17:30');
    await user.click(inSheet.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(hub.calls).toContain('POST /planner/reminders'));
    const sent = hub.bodies.find((b) => b.call === 'POST /planner/reminders')?.body as { text: string; due_at: string };
    expect(sent.text).toBe('Call Lisa');
    expect(new Date(sent.due_at).getTime()).toBe(new Date('2030-03-04T17:30').getTime());
    expect(await screen.findByText('Call Lisa')).toBeInTheDocument();
  });

  it('opens the sheet on the next whole hour, empty, each time; Cancel sends nothing', async () => {
    const hub = seeded();
    renderApp('#/reminders');
    const user = userEvent.setup();
    await screen.findByText('Missed call');
    await user.click(screen.getByRole('button', { name: /New Reminder/ }));
    let sheet = within(await screen.findByRole('dialog', { name: 'New Reminder', hidden: true }));
    expect((sheet.getByLabelText('Time') as HTMLInputElement).value).toMatch(/^\d\d:00$/);
    await user.type(sheet.getByLabelText('Title'), 'draft');
    await user.click(sheet.getByRole('button', { name: 'Cancel' }));
    await user.click(screen.getByRole('button', { name: /New Reminder/ }));
    sheet = within(await screen.findByRole('dialog', { name: 'New Reminder', hidden: true }));
    expect(sheet.getByLabelText('Title')).toHaveValue('');
    expect(hub.calls.some((c) => c.startsWith('POST /planner/reminders'))).toBe(false);
  });

  it('shows the empty state', async () => {
    createFakeHub({ status: SAMPLE_STATUS });
    renderApp('#/reminders');
    expect(await screen.findByText('No reminders.')).toBeInTheDocument();
  });
});
