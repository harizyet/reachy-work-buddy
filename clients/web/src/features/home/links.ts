import type { Ref } from '../../api/home';

/** The existing screen a reference opens. Hash routes, relative, so the dashboard works under /web/ and /hub/web/. */
export function hrefFor(ref: Ref | null | undefined): string {
  switch (ref?.screen) {
    case 'calendar': return '#/calendar';
    case 'tasks': return '#/todo';
    case 'reminders': return '#/reminders';
    case 'notes': return '#/notes';
    case 'meetings': return ref.id ? `#/meetings/${encodeURIComponent(ref.id)}` : '#/meetings';
    case 'talk': return '#/chat';
    default: return '#/';
  }
}
