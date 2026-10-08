import { useId, type InputHTMLAttributes, type ReactNode } from 'react';

const input = 'mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2';

export function Field({ label, hint, children }: { label: ReactNode; hint?: string; children: ReactNode }) {
  return (
    <label className="mb-3 block text-sm">
      {label}
      {children}
      {hint && <small className="block text-[var(--muted)]">{hint}</small>}
    </label>
  );
}

export function TextField({ label, hint, ...props }: { label: ReactNode; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <Field label={label} hint={hint}>
      <input className={input} {...props} />
    </Field>
  );
}

export function Check({ label, checked, onChange, disabled }: { label: ReactNode; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className="mb-3 flex items-center gap-2 text-sm">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

/**
 * A key the hub never sends back: only a masked tail is shown. Typing replaces the saved key, leaving it blank keeps it,
 * and "Remove saved key" deletes it. The typed value is held only in this form's state and dropped when the form resets.
 */
export function SecretField({
  label,
  saved,
  value,
  onValue,
  remove,
  onRemove,
  removeLabel = 'Remove saved key',
  optional,
}: {
  label: string;
  saved: string | null;
  value: string;
  onValue: (v: string) => void;
  remove: boolean;
  onRemove: (v: boolean) => void;
  removeLabel?: string;
  optional?: boolean;
}) {
  const id = useId();
  return (
    <div className="mb-3">
      <label className="block text-sm" htmlFor={id}>
        {label} {optional && <span className="text-[var(--muted)]">(optional)</span>}
      </label>
      <input
        id={id}
        type="password"
        autoComplete="new-password"
        placeholder="Leave blank to keep the saved key"
        className={input}
        value={value}
        onChange={(e) => onValue(e.target.value)}
      />
      <small className="block text-[var(--muted)]">{saved ? `Saved key: ${saved}` : 'No saved key'}</small>
      <Check label={removeLabel} checked={remove} onChange={onRemove} />
    </div>
  );
}

export const selectClass = 'mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2';
