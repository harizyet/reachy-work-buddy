import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

// One page-level status line (aria-live), for outcomes that arrive while the owner is elsewhere,
// such as a background review finishing.
interface NoticeApi {
  notice: string;
  setNotice(text: string): void;
}
const NoticeContext = createContext<NoticeApi | null>(null);

export function NoticeProvider({ children }: { children: ReactNode }) {
  const [notice, setText] = useState('');
  const setNotice = useCallback((text: string) => setText(text), []);
  return (
    <NoticeContext.Provider value={{ notice, setNotice }}>
      <p id="notice" role="status" aria-live="polite" className="mx-auto min-h-5 max-w-5xl px-4 pt-2 text-sm text-[var(--muted)]">
        {notice}
      </p>
      {children}
    </NoticeContext.Provider>
  );
}

export function useNotice(): NoticeApi {
  const value = useContext(NoticeContext);
  if (!value) throw new Error('useNotice needs a NoticeProvider');
  return value;
}
