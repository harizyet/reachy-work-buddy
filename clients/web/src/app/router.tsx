import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Spinner } from '../components/ui/Spinner';
import { LoginPage } from '../features/auth/LoginPage';
import { OverviewPage } from '../features/overview/OverviewPage';
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
