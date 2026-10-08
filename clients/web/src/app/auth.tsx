import { useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { fetchMe, login as apiLogin, logout as apiLogout } from '../api/auth';
import { onUnauthorized } from '../api/client';

type AuthState =
  | { status: 'loading' }
  | { status: 'anonymous'; notice?: string }
  | { status: 'authenticated'; username: string };

interface AuthApi {
  state: AuthState;
  login(username: string, password: string): Promise<void>;
  logout(): Promise<void>;
}

const AuthContext = createContext<AuthApi | null>(null);

// Private data lives only in the TanStack cache and component state. Whenever
// the identity goes away or changes, the whole cache is dropped; nothing is
// persisted to browser storage.
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<AuthState>({ status: 'loading' });

  const clear = useCallback(
    (next: AuthState) => {
      queryClient.clear();
      setState(next);
    },
    [queryClient],
  );

  useEffect(() => {
    const controller = new AbortController();
    fetchMe(controller.signal)
      .then((user) => setState({ status: 'authenticated', username: user.username }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setState({ status: 'anonymous', notice: error instanceof Error && !('status' in error && error.status === 401) ? error.message : undefined });
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(
    () => onUnauthorized(() => clear({ status: 'anonymous', notice: 'Your session has ended. Sign in again.' })),
    [clear],
  );

  const login = useCallback(
    async (username: string, password: string) => {
      const user = await apiLogin(username, password);
      queryClient.clear(); // never carry a previous identity's cache into a new session
      setState({ status: 'authenticated', username: user.username });
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // Local state goes even if the request failed; the cookie then expires on its own.
    }
    clear({ status: 'anonymous' });
  }, [clear]);

  const value = useMemo(() => ({ state, login, logout }), [state, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthApi {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth needs an AuthProvider');
  return value;
}
