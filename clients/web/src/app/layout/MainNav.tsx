import { useEffect, useRef, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';

type Item = { to: string; label: string; end?: boolean };
type Entry = Item | { label: string; items: Item[] };

// Top-level links stay one click away; everything else sits in a category menu.
export const NAV: Entry[] = [
  { to: '/', label: 'Overview', end: true },
  { to: '/chat', label: 'Chat' },
  {
    label: 'Library',
    items: [
      { to: '/meetings', label: 'Meetings' },
      { to: '/notes', label: 'Notes' },
      { to: '/documents', label: 'Documents' },
    ],
  },
  {
    label: 'Planner',
    items: [
      { to: '/todo', label: 'To Do' },
      { to: '/reminders', label: 'Reminders' },
      { to: '/alarms', label: 'Alarms' },
    ],
  },
  {
    label: 'Assistant',
    items: [
      { to: '/memory', label: 'Memory' },
      { to: '/activity', label: 'Activity' },
      { to: '/brain', label: 'Brain' },
      { to: '/coding', label: 'Coding agents' },
    ],
  },
  { to: '/settings', label: 'Settings' },
];

const base = 'rounded-md px-3 py-1.5 text-sm';
const idle = 'hover:bg-[var(--hover)]';
const active = 'bg-[var(--accent)] text-white';

function Group({ label, items }: { label: string; items: Item[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();
  const current = items.some((i) => pathname === i.to || pathname.startsWith(`${i.to}/`));

  // Close after navigating, on an outside click and on Escape.
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={`${base} ${current ? active : idle}`}
      >
        {label} <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul className="absolute left-0 z-20 mt-1 min-w-40 rounded-md border border-[var(--border)] bg-[var(--surface)] p-1 shadow-lg">
          {items.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) => `block ${base} ${isActive ? active : idle}`}
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function MainNav() {
  return (
    <nav aria-label="Main" className="flex flex-1 flex-wrap gap-1">
      {NAV.map((entry) =>
        'items' in entry ? (
          <Group key={entry.label} label={entry.label} items={entry.items} />
        ) : (
          <NavLink
            key={entry.to}
            to={entry.to}
            end={entry.end}
            className={({ isActive }) => `${base} ${isActive ? active : idle}`}
          >
            {entry.label}
          </NavLink>
        ),
      )}
    </nav>
  );
}
