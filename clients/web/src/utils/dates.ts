const DAY_MS = 86_400_000;

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());

/** Whole calendar days from `now` back to `iso` (0 = today, 1 = yesterday, -1 = tomorrow). */
export function daysAgo(iso: string, now: Date): number {
  return Math.round((startOfDay(now).getTime() - startOfDay(new Date(iso)).getTime()) / DAY_MS);
}

/** "Today, 4:00 PM", "Tomorrow, 9:00 AM", otherwise a short date and the time, like the Reminders subtitle. */
export function dueText(iso: string, now: Date = new Date()): string {
  const due = new Date(iso);
  const days = -daysAgo(iso, now);
  const time = due.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const day =
    days === 0 ? 'Today' : days === 1 ? 'Tomorrow' : days === -1 ? 'Yesterday' : due.toLocaleDateString([], { dateStyle: 'short' });
  return `${day}, ${time}`;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** The next whole hour, as the values of a date input and a time input (local time). */
export function nextHourInputs(now: Date = new Date()): { date: string; time: string } {
  const soon = new Date(now.getTime() + 3_600_000);
  soon.setMinutes(0, 0, 0);
  return {
    date: `${soon.getFullYear()}-${pad(soon.getMonth() + 1)}-${pad(soon.getDate())}`,
    time: `${pad(soon.getHours())}:${pad(soon.getMinutes())}`,
  };
}
