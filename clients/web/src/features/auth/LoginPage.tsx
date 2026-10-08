import { useState, type FormEvent } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../app/auth';
import { Button } from '../../components/ui/Button';
import { Spinner } from '../../components/ui/Spinner';

export function LoginPage() {
  const { state, login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  if (state.status === 'loading') return <Spinner label="Checking your session" />;
  if (state.status === 'authenticated') return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await login(username, password);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sign-in failed');
      setBusy(false);
    }
    setPassword(''); // the password never outlives the attempt
  }

  return (
    <main className="mx-auto mt-16 max-w-sm px-4">
      <form onSubmit={submit} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5">
        <span className="block text-[0.7rem] font-medium tracking-widest text-[var(--muted)]">WORK COMPANION</span>
        <h1 className="mb-4 text-xl font-semibold">Sign in to Reachy</h1>
        {state.notice && <p role="status" className="mb-3 text-sm text-[var(--warn)]">{state.notice}</p>}
        <label className="mb-3 block text-sm">
          Username
          <input
            className="mt-1 block w-full rounded-md border border-[var(--border)] bg-[var(--bg)] p-2"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label className="mb-4 block text-sm">
          Password
          <input
            className="mt-1 block w-full rounded-md border border-[var(--border)] bg-[var(--bg)] p-2"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p role="alert" className="mb-3 text-sm text-[var(--bad)]">{error}</p>}
        <Button type="submit" disabled={busy} className="w-full">{busy ? 'Signing in…' : 'Sign in'}</Button>
      </form>
    </main>
  );
}
