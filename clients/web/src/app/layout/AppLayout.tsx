import { NavLink, Outlet } from 'react-router-dom';
import { Button } from '../../components/ui/Button';
import { NoticeProvider } from '../../components/shared/notice';
import { ChatProvider } from '../../features/chat/ChatProvider';
import { DeepReviewProvider } from '../../features/meetings/DeepReview';
import { useAuth } from '../auth';

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/chat', label: 'Chat', end: false },
  { to: '/meetings', label: 'Meetings', end: false },
  { to: '/todo', label: 'To Do', end: false },
  { to: '/reminders', label: 'Reminders', end: false },
  { to: '/alarms', label: 'Alarms', end: false },
  { to: '/notes', label: 'Notes', end: false },
  { to: '/activity', label: 'Activity', end: false },
  { to: '/settings', label: 'Settings', end: false },
];

export function AppLayout() {
  const { state, logout } = useAuth();
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-10 focus:rounded focus:bg-[var(--surface)] focus:p-2">
        Skip to content
      </a>
      <header className="border-b border-[var(--border)] bg-[var(--surface)]">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <div>
            <span className="block text-[0.7rem] font-medium tracking-widest text-[var(--muted)]">WORK COMPANION</span>
            <span className="text-lg font-semibold">Reachy</span>
          </div>
          <nav aria-label="Main" className="flex flex-1 flex-wrap gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm ${isActive ? 'bg-[var(--accent)] text-white' : 'hover:bg-[var(--hover)]'}`
                }
              >
                {item.label}
              </NavLink>
            ))}
            <a className="rounded-md px-3 py-1.5 text-sm hover:bg-[var(--hover)]" href="../ui/">
              Full operator UI ↗
            </a>
          </nav>
          <div className="flex items-center gap-3 text-sm">
            {state.status === 'authenticated' && <span className="text-[var(--muted)]">{state.username}</span>}
            <Button variant="secondary" onClick={() => void logout()}>Log out</Button>
          </div>
        </div>
      </header>
      <NoticeProvider>
        <DeepReviewProvider>
          <main id="main" className="mx-auto max-w-5xl px-4 py-6">
            <ChatProvider>
              <Outlet />
            </ChatProvider>
          </main>
        </DeepReviewProvider>
      </NoticeProvider>
    </div>
  );
}
