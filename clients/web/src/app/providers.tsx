import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { ApiError, StaleSessionError } from '../api/client';
import { AuthProvider } from './auth';

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        // A refused or missing session is not worth retrying; transient failures get one more try.
        retry: (count, error) =>
          !(error instanceof StaleSessionError) && !(error instanceof ApiError && error.status < 500) && count < 1,
        refetchOnWindowFocus: true,
      },
    },
  });
}

export function Providers({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? makeQueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}
