import type { ReactNode } from 'react';
import { ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Spinner } from '../../components/ui/Spinner';

// The Reminders-style card both lists share: coloured title, refresh, status line, body, "New" button.
export function ListShell({
  title,
  accent,
  children,
  onRefresh,
  refreshing,
  error,
  loading,
  onRetry,
  status,
}: {
  title: string;
  accent: string;
  children: ReactNode;
  onRefresh: () => void;
  refreshing: boolean;
  error: string | null;
  loading: boolean;
  onRetry: () => void;
  status: string;
}) {
  return (
    <section className="mx-auto max-w-xl rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4" aria-labelledby="list-title">
      <div className="mb-2 flex items-center justify-between">
        <h1 id="list-title" className="text-2xl font-bold" style={{ color: accent }}>
          {title}
        </h1>
        <Button variant="secondary" onClick={onRefresh} disabled={refreshing}>
          Refresh
        </Button>
      </div>
      <p role="status" className="min-h-5 text-sm text-[var(--bad)]">
        {status}
      </p>
      {loading && <Spinner label="Loading" />}
      {error && <ErrorState message={error} onRetry={onRetry} />}
      {!loading && !error && children}
    </section>
  );
}

export function CompletedToggle({ count, open, onToggle, controls }: { count: number; open: boolean; onToggle: () => void; controls: string }) {
  if (count === 0) return null;
  return (
    <button type="button" className="mt-3 text-sm text-[var(--muted)] underline" aria-expanded={open} aria-controls={controls} onClick={onToggle}>
      {`${count} Completed · ${open ? 'Hide' : 'Show'}`}
    </button>
  );
}

export function RoundCheck({ checked, label, onChange, disabled = false }: { checked: boolean; label: string; onChange: () => void; disabled?: boolean }) {
  return (
    <input
      type="checkbox"
      className="h-5 w-5 shrink-0 cursor-pointer rounded-full accent-[var(--accent)] disabled:cursor-default"
      checked={checked}
      disabled={disabled}
      aria-label={label}
      onChange={onChange}
    />
  );
}

export function DeleteButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" aria-label={label} onClick={onClick} className="rounded px-2 text-[var(--muted)] hover:bg-[var(--hover)]">
      ✕
    </button>
  );
}
