import type { HubStatus, TelegramHealth, UsageCounts } from '../../api/types';
import { EmptyState, ErrorState } from '../../components/shared/states';
import { Card } from '../../components/ui/Card';
import { Spinner } from '../../components/ui/Spinner';
import { StatusPill, type Tone } from '../../components/ui/StatusPill';
import { useStatus } from './useStatus';

interface Row {
  name: string;
  tone: Tone;
  label: string;
}

function telegramRow(t: TelegramHealth): Row {
  if (!t.configured) return { name: 'Telegram', tone: 'warn', label: 'Not configured' };
  if (t.healthy) return { name: 'Telegram', tone: 'good', label: 'Polling' };
  return { name: 'Telegram', tone: 'bad', label: t.last_poll_error ? `Polling failed: ${t.last_poll_error}` : 'Polling stalled' };
}

export function componentRows(status: HubStatus): Row[] {
  const llm: Row =
    status.llm.configured === null
      ? { name: 'Language model', tone: 'bad', label: 'Unavailable' }
      : status.llm.configured
        ? { name: 'Language model', tone: 'good', label: 'Configured' }
        : { name: 'Language model', tone: 'bad', label: 'Not configured' };
  const robots: Row[] = status.robots.length
    ? status.robots.map((r) => ({
        name: r.robot_id,
        tone: r.status === 'ok' ? 'good' : 'bad',
        label: r.status === 'ok' ? (r.embodiment_state ?? 'ok') : 'Unavailable',
      }))
    : [{ name: 'Robots', tone: 'warn', label: 'None registered' }];
  return [
    { name: 'Reachy hub', tone: 'good', label: 'ok' },
    { name: 'Companion core', tone: status.core === 'ok' ? 'good' : 'bad', label: status.core === 'ok' ? 'ok' : 'Unavailable' },
    llm,
    telegramRow(status.telegram),
    ...robots,
  ];
}

function usageLine(c: UsageCounts): string {
  return `${c.calls} calls · ${c.errors} errors · ${c.prompt_tokens} input / ${c.completion_tokens} output tokens`;
}

export function OverviewPage() {
  const { data, error, isPending, isFetching, refetch, dataUpdatedAt } = useStatus();

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <span className="block text-[0.7rem] font-medium tracking-widest text-[var(--muted)]">OVERVIEW</span>
          <h1 className="text-2xl font-semibold">System status</h1>
        </div>
        <p className="text-sm text-[var(--muted)]" role="status">
          {data ? `Updated ${new Date(dataUpdatedAt).toLocaleTimeString()}${isFetching ? ' · refreshing' : ''}` : ''}
          {error && data ? ' · status may be stale' : ''}
        </p>
      </div>
      {isPending && <Spinner label="Loading status" />}
      {error && !data && <ErrorState message={error.message} onRetry={() => void refetch()} />}
      {data && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card eyebrow="HEALTH" title="Components">
            <ul className="divide-y divide-[var(--border)]">
              {componentRows(data).map((row) => (
                <li key={row.name} className="flex items-center justify-between gap-3 py-2">
                  <span>{row.name}</span>
                  <StatusPill tone={row.tone}>{row.label}</StatusPill>
                </li>
              ))}
            </ul>
          </Card>
          <Card eyebrow="LAST 24 HOURS" title="Language model usage">
            {data.llm.usage ? (
              <div className="space-y-2 text-sm">
                <p>{usageLine(data.llm.usage.summary)} · {Math.round(data.llm.usage.summary.avg_latency_ms)} ms average</p>
                {(['local', 'cloud'] as const).map((role) => {
                  const counts = data.llm.usage?.by_role[role];
                  return counts ? <p key={role}>{role}: {usageLine(counts)}</p> : null;
                })}
                {data.llm.usage.summary.calls === 0 && (
                  <EmptyState>No model calls yet. Usage appears after a conversation uses the configured model.</EmptyState>
                )}
              </div>
            ) : (
              <EmptyState>Usage unavailable — companion core is not responding.</EmptyState>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
