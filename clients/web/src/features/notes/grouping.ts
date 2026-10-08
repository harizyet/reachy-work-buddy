import type { Note } from '../../api/types';
import { daysAgo } from '../../utils/dates';

/** Date sections like the iOS list: Today, Yesterday, Previous 7/30 Days, then the month. */
export function sectionOf(iso: string, now: Date = new Date()): string {
  const days = daysAgo(iso, now);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days <= 7) return 'Previous 7 Days';
  if (days <= 30) return 'Previous 30 Days';
  const d = new Date(iso);
  return d.getFullYear() === now.getFullYear()
    ? d.toLocaleDateString([], { month: 'long' })
    : d.toLocaleDateString([], { month: 'long', year: 'numeric' });
}

export function shortDate(iso: string, now: Date = new Date()): string {
  const days = daysAgo(iso, now);
  const d = new Date(iso);
  if (days <= 0) return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  if (days === 1) return 'Yesterday';
  if (days <= 7) return d.toLocaleDateString([], { weekday: 'long' });
  return d.toLocaleDateString([], { dateStyle: 'short' });
}

export const preview = (note: Note): string =>
  note.body
    .split('\n')
    .map((line) => line.trim())
    .find(Boolean) || 'No additional text';

export function groupNotes(notes: Note[], now: Date = new Date()): [string, Note[]][] {
  const sorted = [...notes].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
  const groups = new Map<string, Note[]>();
  for (const note of sorted) {
    const name = sectionOf(note.updated_at, now);
    groups.set(name, [...(groups.get(name) ?? []), note]);
  }
  return [...groups];
}
