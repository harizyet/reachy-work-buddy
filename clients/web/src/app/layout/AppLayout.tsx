import { Outlet } from 'react-router-dom';
import { Button } from '../../components/ui/Button';
import { NoticeProvider } from '../../components/shared/notice';
import { ChatProvider } from '../../features/chat/ChatProvider';
import { VoiceProvider } from '../../features/voice/VoiceProvider';
import { DeepReviewProvider } from '../../features/meetings/DeepReview';
import { useAuth } from '../auth';
import { MainNav } from './MainNav';

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
          <MainNav />
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
              <VoiceProvider>
                <Outlet />
              </VoiceProvider>
            </ChatProvider>
          </main>
        </DeepReviewProvider>
      </NoticeProvider>
    </div>
  );
}
