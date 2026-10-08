import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

afterEach(() => vi.unstubAllGlobals());

// Cases from the legacy tab (clients/operator-ui/tests/alarms.test.cjs). Times are built in local time
// so the assertions hold in any zone.
const local = (day: string, h: number, m: number) => new Date(`${day}T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`).toISOString();

function seeded() {
  return createFakeHub({
    status: SAMPLE_STATUS,
    stations: [{ id: 's1', name: '<b>Jazz FM</b>', guide_id: 's111' }],
    alarms: [
      { id: 'a1', label: '<img src=x onerror=boom()> wake', due_at: local('2030-01-03', 7, 0), station_id: 's1', status: 'scheduled', volume: 150, repeat: [0, 1, 2, 3, 4], enabled: true, delivery: null },
      { id: 'a2', label: 'early', due_at: local('2030-01-03', 6, 15), station_id: null, status: 'fired', volume: 100, repeat: [], enabled: false, delivery: 'telegram: privacy mode' },
      { id: 'a3', label: 'gone', due_at: local('2030-01-03', 5, 0), station_id: null, status: 'cancelled', volume: 100, repeat: [], enabled: false, delivery: null },
    ],
    search: [{ guide_id: 's222', name: '<i>Rock</i>', detail: 'hits' }],
  });
}

describe('Alarms', () => {
  it('lists alarms by time of day with repeat, station, volume and last delivery; cancelled ones are hidden; text is literal', async () => {
    seeded();
    const { container } = renderApp('#/alarms');
    const early = await screen.findByRole('switch', { name: /early 6:15/ });
    const wake = screen.getByRole('switch', { name: /wake 7:00/ });
    const rows = screen.getAllByRole('listitem').filter((li) => li.querySelector('[role=switch]'));
    expect(rows).toHaveLength(2);
    expect(rows[0]).toContainElement(early);
    expect(rows[0]).toHaveTextContent(/6:15\s*AM/);
    expect(rows[0]).toHaveTextContent('last: telegram: privacy mode');
    expect(rows[1]).toHaveTextContent(/7:00\s*AM/);
    expect(rows[1]).toHaveTextContent('<img src=x onerror=boom()> wake, Weekdays');
    expect(rows[1]).toHaveTextContent('<b>Jazz FM</b> · 150% volume');
    expect(container.querySelector('img, b, i')).toBeNull();
    expect(wake).toBeChecked();
    expect(early).not.toBeChecked();
    expect(screen.queryByText(/gone/)).not.toBeInTheDocument();
  });

  it('switches an alarm on and off through PATCH enabled', async () => {
    const hub = seeded();
    renderApp('#/alarms');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('switch', { name: /early 6:15/ }));
    await waitFor(() => expect(hub.calls).toContain('PATCH /planner/alarms/a2'));
    expect(hub.bodies.find((b) => b.call === 'PATCH /planner/alarms/a2')?.body).toEqual({ enabled: true });
    await user.click(screen.getByRole('switch', { name: /wake 7:00/ }));
    await waitFor(() => expect(hub.data.alarms[0]!.enabled).toBe(false));
  });

  it('adds an alarm from the sheet with time, repeat days, label, sound and volume', async () => {
    const hub = seeded();
    renderApp('#/alarms');
    const user = userEvent.setup();
    await screen.findByRole('switch', { name: /early/ });
    await user.click(screen.getByRole('button', { name: 'Add alarm' }));
    const sheet = within(await screen.findByRole('dialog', { name: 'Add Alarm', hidden: true }));
    await user.selectOptions(sheet.getByLabelText('Hour'), '5');
    await user.selectOptions(sheet.getByLabelText('Minute'), '30');
    await user.selectOptions(sheet.getByLabelText('AM or PM'), 'PM');
    await user.click(sheet.getByRole('button', { name: 'Mon' }));
    await user.click(sheet.getByRole('button', { name: 'Wed' }));
    expect(sheet.getByText('Mon, Wed')).toBeInTheDocument();
    await user.clear(sheet.getByLabelText('Label'));
    await user.type(sheet.getByLabelText('Label'), 'cake');
    await user.selectOptions(sheet.getByLabelText('Sound'), 's1');
    const volume = sheet.getByLabelText(/Volume/) as HTMLInputElement;
    fireEvent.change(volume, { target: { value: '250' } }); // a range input has no typing; jsdom ignores arrow keys
    expect(sheet.getByTestId('volume-value')).toHaveTextContent('250%');
    await user.click(sheet.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(hub.calls).toContain('POST /planner/alarms'));
    const sent = hub.bodies.find((b) => b.call === 'POST /planner/alarms')!.body as { volume: number };
    expect(sent).toMatchObject({ label: 'cake', time: '17:30', repeat: [0, 2], station_id: 's1' });
    expect(sent.volume).toBe(250);
    expect(await screen.findByRole('switch', { name: /cake 5:30/ })).toBeChecked();
  });

  it('edits an alarm (sheet starts from its values), and deletes from the sheet', async () => {
    const hub = seeded();
    renderApp('#/alarms');
    const user = userEvent.setup();
    await user.click(await screen.findByText('<img src=x onerror=boom()> wake, Weekdays'));
    const sheet = within(await screen.findByRole('dialog', { name: 'Edit Alarm', hidden: true }));
    expect(sheet.getByLabelText('Hour')).toHaveValue('7');
    expect(sheet.getByLabelText('AM or PM')).toHaveValue('AM');
    expect(sheet.getByText('Weekdays')).toBeInTheDocument();
    await user.selectOptions(sheet.getByLabelText('Minute'), '45');
    await user.click(sheet.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(hub.calls).toContain('PATCH /planner/alarms/a1'));
    expect(hub.bodies.find((b) => b.call === 'PATCH /planner/alarms/a1')?.body).toMatchObject({ time: '07:45', repeat: [0, 1, 2, 3, 4], station_id: 's1', volume: 150 });

    await user.click(await screen.findByText(/wake, Weekdays/));
    await user.click(within(await screen.findByRole('dialog', { name: 'Edit Alarm', hidden: true })).getByRole('button', { name: 'Delete Alarm' }));
    await waitFor(() => expect(hub.calls).toContain('DELETE /planner/alarms/a1'));
    await waitFor(() => expect(screen.queryByRole('switch', { name: /wake/ })).not.toBeInTheDocument());
  });

  it('Edit mode shows a delete control per row; Done hides them', async () => {
    const hub = seeded();
    renderApp('#/alarms');
    const user = userEvent.setup();
    await screen.findByRole('switch', { name: /early/ });
    await user.click(screen.getByRole('button', { name: 'Edit' }));
    expect(screen.getAllByRole('button', { name: /^Delete alarm / })).toHaveLength(2);
    await user.click(screen.getAllByRole('button', { name: /^Delete alarm / })[0]!);
    await waitFor(() => expect(hub.calls).toContain('DELETE /planner/alarms/a2'));
    await user.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.queryByRole('button', { name: /^Delete alarm / })).not.toBeInTheDocument();
  });

  it('Stop alarm reports whether anything was playing', async () => {
    const hub = seeded();
    renderApp('#/alarms');
    const user = userEvent.setup();
    await screen.findByRole('switch', { name: /early/ });
    await user.click(screen.getByRole('button', { name: 'Stop alarm' }));
    expect(await screen.findByText('Alarm stopped.')).toBeInTheDocument();
    expect(hub.calls).toContain('POST /planner/alarms/stop');
    hub.respond((c) => c === 'POST /planner/alarms/stop', () => jsonResponse({ stopped: false }));
    await user.click(screen.getByRole('button', { name: 'Stop alarm' }));
    expect(await screen.findByText('No alarm is playing.')).toBeInTheDocument();
  });

  it('searches TuneIn, saves a station, and removes a saved station; results render literally', async () => {
    const hub = seeded();
    const { container } = renderApp('#/alarms');
    const user = userEvent.setup();
    await screen.findByRole('switch', { name: /early/ });
    await user.type(screen.getByLabelText('Find a station'), 'r'); // one character: not sent
    await user.click(screen.getByRole('button', { name: 'Search' }));
    expect(hub.calls.some((c) => c.includes('stations/search'))).toBe(false);
    await user.type(screen.getByLabelText('Find a station'), 'ock');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    expect(await screen.findByText('<i>Rock</i>')).toBeInTheDocument();
    expect(hub.calls).toContain('GET /planner/stations/search?q=rock');
    expect(container.querySelector('i')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Save station <i>Rock</i>' }));
    await waitFor(() => expect(hub.bodies.find((b) => b.call === 'POST /planner/stations')?.body).toEqual({ name: '<i>Rock</i>', guide_id: 's222' }));
    expect(await screen.findAllByText('<i>Rock</i>')).not.toHaveLength(0);
    await user.click(screen.getByRole('button', { name: 'Remove station <b>Jazz FM</b>' }));
    await waitFor(() => expect(hub.calls).toContain('DELETE /planner/stations/s1'));
  });

  it('shows a search failure, and the empty states', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    renderApp('#/alarms');
    const user = userEvent.setup();
    expect(await screen.findByText('No alarms.')).toBeInTheDocument();
    expect(screen.getByText('No saved stations.')).toBeInTheDocument();
    hub.respond((c) => c.includes('stations/search'), () => jsonResponse({ detail: 'Station search unavailable' }, 502));
    await user.type(screen.getByLabelText('Find a station'), 'jazz');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Station search unavailable');
  });
});
