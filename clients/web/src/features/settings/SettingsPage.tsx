import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { AssistantTab } from './AssistantTab';
import { ModelsTab } from './ModelsTab';
import { SearchTab } from './SearchTab';
import { VoiceTab } from './VoiceTab';

export interface SettingsTab {
  id: string;
  label: string;
  panel: ReactNode;
}

const TABS: SettingsTab[] = [
  { id: 'assistant', label: 'Assistant', panel: <AssistantTab /> },
  { id: 'models', label: 'Models', panel: <ModelsTab /> },
  { id: 'search', label: 'Web search', panel: <SearchTab /> },
  { id: 'voice', label: 'Voice & motion', panel: <VoiceTab /> },
];

// Settings tabs follow the WAI-ARIA tabs pattern (arrow keys, Home and End move focus and selection) like the legacy page.
export function SettingsPage() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const current = TABS.find((t) => t.id === tab);
  if (!current) return <Navigate to={`/settings/${TABS[0]!.id}`} replace />;

  function move(event: KeyboardEvent, index: number) {
    let next = index;
    if (event.key === 'ArrowRight') next = (index + 1) % TABS.length;
    else if (event.key === 'ArrowLeft') next = (index + TABS.length - 1) % TABS.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = TABS.length - 1;
    else return;
    event.preventDefault();
    const target = TABS[next]!;
    navigate(`/settings/${target.id}`);
    refs.current[target.id]?.focus();
  }

  return (
    <div>
      <div className="mb-4">
        <span className="block text-[0.7rem] font-medium tracking-widest text-[var(--muted)]">PREFERENCES &amp; CONNECTIONS</span>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-sm text-[var(--muted)]">Configure your assistant and its connected features.</p>
      </div>
      <div role="tablist" aria-label="Feature settings" className="mb-4 flex flex-wrap gap-1">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => { refs.current[t.id] = el; }}
            id={`settings-${t.id}-tab`}
            role="tab"
            aria-selected={t.id === current.id}
            aria-controls={`settings-${t.id}`}
            tabIndex={t.id === current.id ? 0 : -1}
            className={`rounded-md px-3 py-1.5 text-sm ${t.id === current.id ? 'bg-[var(--accent)] text-white' : 'border border-[var(--border)] hover:bg-[var(--hover)]'}`}
            onClick={() => navigate(`/settings/${t.id}`)}
            onKeyDown={(e) => move(e, i)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div id={`settings-${current.id}`} role="tabpanel" aria-labelledby={`settings-${current.id}-tab`}>
        {current.panel}
      </div>
    </div>
  );
}
