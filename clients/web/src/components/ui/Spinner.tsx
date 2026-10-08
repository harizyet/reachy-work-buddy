export function Spinner({ label }: { label: string }) {
  return (
    <p role="status" className="py-10 text-center text-[var(--muted)]">
      {label}…
    </p>
  );
}
