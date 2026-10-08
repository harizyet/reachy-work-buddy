import type { ButtonHTMLAttributes } from 'react';

type Variant = 'primary' | 'secondary';

export function Button({ variant = 'primary', className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const look =
    variant === 'primary'
      ? 'bg-[var(--accent)] text-white hover:opacity-90'
      : 'border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--hover)]';
  return (
    <button
      type="button"
      className={`rounded-md px-3 py-1.5 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:opacity-50 ${look} ${className}`}
      {...props}
    />
  );
}
