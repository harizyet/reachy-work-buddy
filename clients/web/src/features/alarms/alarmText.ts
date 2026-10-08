import type { Alarm } from '../../api/types';
import { daysAgo } from '../../utils/dates';

export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']; // 0 = Monday, as the server counts

export function repeatText(days: number[]): string {
  const sorted = [...days].sort((a, b) => a - b);
  const key = sorted.join();
  if (!key) return '';
  if (key === '0,1,2,3,4,5,6') return 'Every day';
  if (key === '0,1,2,3,4') return 'Weekdays';
  if (key === '5,6') return 'Weekends';
  return sorted.map((d) => DAYS[d] ?? '?').join(', ');
}

export function timeParts(iso: string): { time: string; suffix: string } {
  const parts = new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' }).formatToParts(new Date(iso));
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return { time: `${part('hour')}:${part('minute')}`, suffix: part('dayPeriod') };
}

export function dayLabel(iso: string, now: Date = new Date()): string {
  const days = -daysAgo(iso, now);
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  return new Date(iso).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
}

export const isOn = (alarm: Alarm) => alarm.enabled && alarm.status === 'scheduled';

const minuteOfDay = (a: Alarm) => {
  const d = new Date(a.due_at);
  return d.getHours() * 60 + d.getMinutes();
};
export const byTimeOfDay = (a: Alarm, b: Alarm) => minuteOfDay(a) - minuteOfDay(b);

export function wheelTime(hour12: number, minute: number, pm: boolean): string {
  const h = (hour12 % 12) + (pm ? 12 : 0);
  return `${String(h).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}
