import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Spinner } from '../components/ui/Spinner';
import { ActivityPage } from '../features/activity/ActivityPage';
import { LoginPage } from '../features/auth/LoginPage';
import { AlarmsPage } from '../features/alarms/AlarmsPage';
import { ChatPage } from '../features/chat/ChatPage';
import { NotesPage } from '../features/notes/NotesPage';
import { OverviewPage } from '../features/overview/OverviewPage';
import { RemindersPage } from '../features/planner/RemindersPage';
import { TodoPage } from '../features/planner/TodoPage';
import { useAuth } from './auth';
import { AppLayout } from './layout/AppLayout';

function Protected() {
  const { state } = useAuth();
  // Nothing private renders until the hub has confirmed the owner session.
  if (state.status === 'loading') return <Spinner label="Checking your session" />;
  if (state.status === 'anonymous') return <Navigate to="/login" replace />;
  return <AppLayout />;
}

function NotFound() {
  return (
    <div className="py-16 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <a className="mt-3 inline-block underline" href="#/">Back to Overview</a>
    </div>
  );
}

// Hash routing keeps the app working under /web/ and /hub/web/ with no server
// fallback route, and keeps routes out of paths the hub's static mount serves.
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Protected />}>
        <Route index element={<OverviewPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="todo" element={<TodoPage />} />
        <Route path="reminders" element={<RemindersPage />} />
        <Route path="alarms" element={<AlarmsPage />} />
        <Route path="notes" element={<NotesPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

export function AppRouter() {
  return (
    <HashRouter>
      <AppRoutes />
    </HashRouter>
  );
}
