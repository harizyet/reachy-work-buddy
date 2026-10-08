import type { HubStatus, TelegramHealth, UsageCounts } from '../../api/types';
import { EmptyState, ErrorState } from '../../components/shared/states';
import { Card } from '../../components/ui/Card';
import { Spinner } from '../../components/ui/Spinner';
import { StatusPill, type Tone } from '../../components/ui/StatusPill';
import { useQuery } from '@tanstack/react-query';
import { fetchAudit, fetchNotifications } from '../../api/status';
import { useChat } from '../chat/ChatProvider';
import { Meters } from '../settings/SearchTab';
import { useSearchLog } from '../settings/useSettings';
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
              </div>
            ) : (
              <EmptyState>Usage unavailable — companion core is not responding.</EmptyState>
            )}
          </Card>
          <Card eyebrow="GROUNDING" title="Search API usage">
            <SearchUsage />
          </Card>
          <ActivityCards />
          <div className="md:col-span-2">
            <UsageTable usage={data.llm.usage} />
          </div>
        </div>
      )}
    </div>
  );
}

function SearchUsage() {
  const log = useSearchLog(true);
  if (log.error) return <EmptyState>{log.error.message}</EmptyState>;
  return <Meters usage={log.data?.usage ?? null} />;
}

// Delivery decisions and notifications waiting for the owner's user.
function ActivityCards() {
  const chat = useChat();
  const audit = useQuery({ queryKey: ['overview', 'audit', chat.user], queryFn: ({ signal }) => fetchAudit(chat.user as string, signal), enabled: chat.user !== null, retry: false });
  const queued = useQuery({ queryKey: ['overview', 'notifications', chat.user], queryFn: ({ signal }) => fetchNotifications(chat.user as string, signal), enabled: chat.user !== null, retry: false });
  return (
    <>
      <Card title="Recent activity">
        <ul className="text-sm">
          {(audit.data ?? []).map((e, i) => <li key={i}>{`${e.action || 'response'} · ${e.reason || e.delivery_channel || ''}`}</li>)}
          {audit.data?.length === 0 && <li>Nothing here yet.</li>}
          {audit.error && <li>{audit.error.message}</li>}
        </ul>
      </Card>
      <Card title="Queued notifications">
        <ul className="text-sm">
          {(queued.data ?? []).map((e, i) => <li key={i}>{e.text || e.reason || 'Queued notification'}</li>)}
          {queued.data?.length === 0 && <li>Nothing here yet.</li>}
          {queued.error && <li>{queued.error.message}</li>}
        </ul>
      </Card>
    </>
  );
}

function UsageTable({ usage }: { usage: HubStatus['llm']['usage'] }) {
  return (
    <Card eyebrow="LAST 24 HOURS" title="LLM utilization">
      {!usage ? (
        <EmptyState>Usage unavailable — companion core is not responding.</EmptyState>
      ) : (
        <>
          {usage.latest_escalation && (
            <p className="mb-2 text-sm">{`Latest escalation: ${usage.latest_escalation.reason === 'manual' ? 'manual request' : 'local error'} · ${new Date(usage.latest_escalation.at).toLocaleString()}`}</p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr><th className="pr-3">Time</th><th className="pr-3">Role / model</th><th className="pr-3">Result</th><th className="pr-3">Input / output tokens</th><th>Latency</th></tr>
              </thead>
              <tbody>
                {usage.entries.map((e, i) => (
                  <tr key={i} className="border-t border-[var(--border)]">
                    <td className="pr-3">{new Date(e.at).toLocaleString()}</td>
                    <td className="pr-3 break-words">{`${e.role} / ${e.model}`}</td>
                    <td className="pr-3 break-words">{e.success ? 'Success' : (e.error_message ?? 'Failed')}</td>
                    <td className="pr-3">{`${e.prompt_tokens ?? '—'} / ${e.completion_tokens ?? '—'}`}</td>
                    <td>{`${Math.round(e.latency_ms)} ms`}</td>
                  </tr>
                ))}
                {usage.entries.length === 0 && (
                  <tr><td colSpan={5}>No model calls yet. Usage appears after a conversation uses the configured model.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}
