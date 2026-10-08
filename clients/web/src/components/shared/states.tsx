import type { ReactNode } from 'react';
import { Button } from '../ui/Button';

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-[var(--bad)] bg-[var(--bad-bg)] p-4">
      <p className="font-medium text-[var(--bad)]">Something went wrong</p>
      {/* Server text is rendered as plain text by React; never as HTML. */}
      <p className="mt-1 text-sm">{message}</p>
      {onRetry && <Button variant="secondary" className="mt-3" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-4 text-sm text-[var(--muted)]">{children}</p>;
}
