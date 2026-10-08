export type Tone = 'good' | 'warn' | 'bad';

const TONES: Record<Tone, string> = {
  good: 'bg-[var(--good-bg)] text-[var(--good)]',
  warn: 'bg-[var(--warn-bg)] text-[var(--warn)]',
  bad: 'bg-[var(--bad-bg)] text-[var(--bad)]',
};
// The glyph keeps the state readable without colour.
const GLYPHS: Record<Tone, string> = { good: '●', warn: '▲', bad: '✕' };

export function StatusPill({ tone, children }: { tone: Tone; children: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      <span aria-hidden="true">{GLYPHS[tone]}</span>
      {children}
    </span>
  );
}
