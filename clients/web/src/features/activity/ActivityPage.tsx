import { useQuery } from '@tanstack/react-query';
import { listReceipts } from '../../api/planner';
import type { Receipt } from '../../api/types';
import { EmptyState, ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Spinner } from '../../components/ui/Spinner';

// "task.created" reads "Task · created"; only the first dot is replaced, as in the legacy tab.
export const receiptTitle = (r: Receipt) => r.action_type.replace('.', ' · ').replace(/^./, (c) => c.toUpperCase());

export function receiptDetail(r: Receipt): string {
  return [
    new Date(r.at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }),
    r.source_channel,
    r.status === 'failed' ? `failed${r.failure_reason ? ': ' + r.failure_reason : ''}` : '',
    ...Object.entries(r.fields).map(([key, value]) => `${key}: ${value}`),
  ]
    .filter(Boolean)
    .join(' · ');
}

export function ActivityPage() {
  const receipts = useQuery({ queryKey: ['planner', 'receipts'], queryFn: ({ signal }) => listReceipts(signal), refetchOnMount: 'always' });
  return (
    <Card eyebrow="WHAT REACHY DID" title="Recent activity">
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="text-sm text-[var(--muted)]">
          Receipts are recorded by the assistant when it changes something, independent of how it phrased the reply.
        </p>
        <Button variant="secondary" onClick={() => void receipts.refetch()} disabled={receipts.isFetching}>
          Refresh
        </Button>
      </div>
      {receipts.isPending && <Spinner label="Loading activity" />}
      {receipts.error && <ErrorState message={receipts.error.message} onRetry={() => void receipts.refetch()} />}
      {receipts.data && receipts.data.length === 0 && <EmptyState>No recent activity.</EmptyState>}
      {receipts.data && (
        <ul className="divide-y divide-[var(--border)]">
          {receipts.data.map((r) => (
            <li key={r.id} className="py-2">
              <span className={r.status === 'failed' ? 'text-[var(--muted)] line-through' : ''}>{receiptTitle(r)}</span>
              <br />
              <span className="break-words text-sm text-[var(--muted)]">{receiptDetail(r)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
