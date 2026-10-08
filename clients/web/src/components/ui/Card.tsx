import type { ReactNode } from 'react';

export function Card({ title, eyebrow, children }: { title: string; eyebrow?: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4" aria-label={title}>
      {eyebrow && <span className="block text-[0.7rem] font-medium tracking-widest text-[var(--muted)]">{eyebrow}</span>}
      <h2 className="mb-3 text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}
