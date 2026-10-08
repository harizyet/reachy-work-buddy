import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { receiptDetail, receiptTitle } from '../src/features/activity/ActivityPage';
import { createFakeHub, jsonResponse, type FakeReceipt } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

afterEach(() => vi.unstubAllGlobals());

const receipts: FakeReceipt[] = [
  { id: 'r1', action_type: 'task.created', status: 'success', at: '2030-01-02T07:00:00Z', source_channel: 'web', fields: { Task: '<img src=x onerror=boom()>' }, failure_reason: null },
  { id: 'r2', action_type: 'alarm.delivered', status: 'failed', at: '2030-01-02T06:00:00Z', source_channel: 'system', fields: {}, failure_reason: 'failed: no audio' },
];

describe('Activity', () => {
  it('lists receipts with literal text and failure reasons', async () => {
    createFakeHub({ status: SAMPLE_STATUS, receipts });
    const { container } = renderApp('#/activity');
    expect(await screen.findByText('Task · created')).toBeInTheDocument();
    expect(screen.getByText(/Task: <img src=x onerror=boom\(\)>/)).toBeInTheDocument();
    expect(screen.getByText(/failed: failed: no audio/)).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('Alarm · delivered')).toHaveClass('line-through');
    expect(screen.getByText('Task · created')).not.toHaveClass('line-through');
  });

  it('formats titles and details like the legacy tab', () => {
    const [created, failed] = receipts as [FakeReceipt, FakeReceipt];
    expect(receiptTitle(created)).toBe('Task · created');
    expect(receiptTitle({ ...created, action_type: 'a.b.c' })).toBe('A · b.c'); // only the first dot
    expect(receiptDetail(failed)).toMatch(/system · failed: failed: no audio$/);
    expect(receiptDetail({ ...failed, failure_reason: null })).toMatch(/system · failed$/);
  });

  it('shows the empty state, and reloads on Refresh', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    renderApp('#/activity');
    expect(await screen.findByText('No recent activity.')).toBeInTheDocument();
    hub.data.receipts.push(receipts[0]!);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Refresh' }));
    expect(await screen.findByText('Task · created')).toBeInTheDocument();
    expect(hub.calls.filter((c) => c === 'GET /planner/receipts')).toHaveLength(2);
  });

  it('shows a load error with retry', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    hub.respond((c) => c === 'GET /planner/receipts', () => jsonResponse({ detail: 'Companion core unavailable' }, 502));
    renderApp('#/activity');
    expect(await screen.findByRole('alert')).toHaveTextContent('Companion core unavailable');
    hub.clearOverrides();
    hub.data.receipts.push(receipts[0]!);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(screen.getByText('Task · created')).toBeInTheDocument());
  });
});
