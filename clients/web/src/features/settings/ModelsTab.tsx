import { useState, type FormEvent } from 'react';
import { StaleSessionError } from '../../api/client';
import type { LlmConfig, ProviderConfig } from '../../api/types';
import { useNotice } from '../../components/shared/notice';
import { ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Spinner } from '../../components/ui/Spinner';
import { Field, SecretField, TextField, selectClass } from './fields';
import { useLlm, useSaveLlm } from './useSettings';

export function ModelsTab() {
  const llm = useLlm();
  // A save always starts the form afresh, even when the hub answers with exactly what it held before; otherwise a
  // key the owner just typed would stay in the password field after being saved.
  const [saves, setSaves] = useState(0);
  return (
    <Card eyebrow="INFERENCE" title="Language model">
      <p className="mb-3 text-sm">Connect a local server or a hosted compatible endpoint. Changes apply to the next conversation turn.</p>
      {llm.isPending && <Spinner label="Loading model settings" />}
      {llm.error && !llm.data && <ErrorState message={llm.error.message} onRetry={() => void llm.refetch()} />}
      {llm.data && <ModelForm key={`${saves}|${JSON.stringify(llm.data)}`} initial={llm.data} onSaved={() => setSaves((n) => n + 1)} />}
    </Card>
  );
}

interface Draft {
  baseUrl: string;
  model: string;
  key: string;
  removeKey: boolean;
}
const draftOf = (p: ProviderConfig | null): Draft => ({ baseUrl: p?.base_url ?? '', model: p?.model ?? '', key: '', removeKey: false });

// "No URL and no model" removes the provider; a half-filled one is refused before anything is sent.
function providerBody(d: Draft): Record<string, unknown> | null {
  const base_url = d.baseUrl.trim();
  const model = d.model.trim();
  if (!base_url && !model) return null;
  if (!base_url || !model) throw new Error('Each provider needs both a URL and model name.');
  const value: Record<string, unknown> = { base_url, model };
  if (d.removeKey) value.api_key = null;
  else if (d.key) value.api_key = d.key;
  return value;
}

function ModelForm({ initial, onSaved }: { initial: LlmConfig; onSaved: () => void }) {
  const save = useSaveLlm();
  const { setNotice } = useNotice();
  const [local, setLocal] = useState(draftOf(initial.local));
  const [cloud, setCloud] = useState(draftOf(initial.cloud));
  const [routing, setRouting] = useState(initial.routing);
  const [edited, setEdited] = useState(false);
  const [problem, setProblem] = useState('');

  // Filling in a first cloud provider suggests a routing, until the owner picks one.
  function cloudChange(next: Draft) {
    setCloud(next);
    if (!initial.cloud && !edited) setRouting(local.baseUrl.trim() ? 'local_with_cloud_fallback' : 'cloud_only');
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setProblem('');
    let body;
    try {
      body = { local: providerBody(local), cloud: providerBody(cloud), routing: { mode: routing } };
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Invalid settings');
      return;
    }
    save.mutate(body, { onSuccess: () => (setNotice('Model settings saved.'), onSaved()) });
  }

  const error = problem || (save.error && !(save.error instanceof StaleSessionError) ? save.error.message : '');
  return (
    <form onSubmit={submit}>
      <TextField label="Base URL" type="url" placeholder="http://ovms-host:8000/v1" value={local.baseUrl} onChange={(e) => setLocal({ ...local, baseUrl: e.target.value })} />
      <TextField
        label="Model name"
        placeholder="Model name configured on your server"
        hint="For OpenVINO Model Server, use its exact configured model name."
        value={local.model}
        onChange={(e) => setLocal({ ...local, model: e.target.value })}
      />
      <SecretField label="API key" optional saved={initial.local?.api_key ?? null} value={local.key} onValue={(key) => setLocal({ ...local, key })} remove={local.removeKey} onRemove={(removeKey) => setLocal({ ...local, removeKey })} />

      <h3 className="mb-2 font-medium">Cloud provider (optional)</h3>
      <TextField label="Cloud base URL" type="url" placeholder="https://provider.example/v1" value={cloud.baseUrl} onChange={(e) => cloudChange({ ...cloud, baseUrl: e.target.value })} />
      <TextField label="Cloud model" value={cloud.model} onChange={(e) => cloudChange({ ...cloud, model: e.target.value })} />
      <SecretField label="Cloud API key" saved={initial.cloud?.api_key ?? null} value={cloud.key} onValue={(key) => setCloud({ ...cloud, key })} remove={cloud.removeKey} onRemove={(removeKey) => setCloud({ ...cloud, removeKey })} removeLabel="Remove saved cloud key" />
      <Field label="Routing">
        <select
          className={selectClass}
          value={routing}
          onChange={(e) => {
            setEdited(true);
            setRouting(e.target.value);
          }}
        >
          <option value="local_only">Local only</option>
          <option value="local_with_cloud_fallback">Local, then cloud on failure</option>
          <option value="cloud_only">Cloud only</option>
        </select>
      </Field>
      <p className="mb-3 text-sm text-[var(--muted)]">
        Cloud routing sends the conversation context to that provider. Blank URL and model remove a provider; blank keys retain saved credentials.
      </p>
      {error && <p role="alert" className="mb-2 text-sm text-[var(--bad)]">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          Save model
        </Button>
        <Button variant="secondary" disabled={save.isPending} onClick={() => save.mutate({ local: null, cloud: null, routing: { mode: 'local_only' } }, { onSuccess: () => (setNotice('Model disabled.'), onSaved()) })}>
          Disable all models
        </Button>
      </div>
    </form>
  );
}
