/* Phase 29.19: provider credentials (e.g. a Claude Code API key) never
   enter localStorage, and the value is never echoed back once saved —
   only provider/kind/last four characters/updated_at come back from the
   server. */
function createCodingAgents({api, isLoggedIn}) {
  const el = id => document.getElementById(id);
  const root = '/providers';
  const PROVIDERS = [
    {
      id: 'claude-code', title: 'Claude Code',
      hint: 'API key: pay-per-use billing from your Anthropic Console account. OAuth token: if you have a Claude Pro or Max subscription, run "claude setup-token" on a computer where you can sign in, then paste the token it prints here — usage counts against your subscription instead of API billing. Reachy cannot run that sign-in step itself. Starting a session with an OAuth token is disabled for now, so your subscription cannot be spent by this feature yet; only an API key can actually run a task at this stage.',
    },
    {
      id: 'claude-code-account', title: 'Claude account usage', fixedKind: 'oauth_token',
      hint: 'Optional, read-only: lets Reachy show your live 5-hour and weekly Claude allowance. The session token above cannot do this. Paste the contents of the .credentials.json file that "claude login" creates (or its claudeAiOauth object). Use a separate login so it does not share a refresh token with your own computer: run CLAUDE_CONFIG_DIR=/tmp/reachy-login claude login, then paste /tmp/reachy-login/.credentials.json. Reachy refreshes and re-saves this credential itself, and only ever uses it to read usage.',
    },
    {id: 'codex', title: 'OpenAI Codex CLI'},
  ];
  function say(text) { el('coding-agents-status').textContent = text; }
  function reset() {
    el('coding-agent-cards').replaceChildren();
  }
  function render(records) {
    if (!isLoggedIn()) return;
    const byProvider = Object.fromEntries(records.map(r => [r.provider, r]));
    el('coding-agent-cards').replaceChildren();
    for (const {id, title, hint, fixedKind} of PROVIDERS) {
      const record = byProvider[id];
      const card = document.createElement('section'); card.className = 'card';
      const heading = document.createElement('h3'); heading.textContent = title;
      const status = document.createElement('p');
      status.textContent = record
        ? 'Credential configured (ending ' + record.last_four + '). Saved ' + new Date(record.updated_at).toLocaleString() + '.'
        : 'No credential configured yet.';
      card.append(heading, status);
      if (hint) { const hintPara = document.createElement('p'); hintPara.className = 'muted'; hintPara.textContent = hint; card.append(hintPara); }

      const form = document.createElement('form');
      const kindLabel = document.createElement('label'); kindLabel.textContent = 'Credential type';
      const kindSelect = document.createElement('select');
      for (const [value, text] of [['api_key', 'API key'], ['oauth_token', 'OAuth token']]) {
        const option = document.createElement('option'); option.value = value; option.textContent = text;
        kindSelect.append(option);
      }
      kindLabel.append(kindSelect);
      if (fixedKind) { kindSelect.value = fixedKind; kindLabel.hidden = true; }
      const valueLabel = document.createElement('label'); valueLabel.textContent = title + ' credential value';
      const valueInput = document.createElement('input');
      valueInput.type = 'password'; valueInput.autocomplete = 'off'; valueInput.required = true; valueInput.maxLength = 8192;
      valueLabel.append(valueInput);
      const saveButton = document.createElement('button'); saveButton.textContent = record ? 'Replace credential' : 'Save credential';
      form.append(kindLabel, valueLabel, saveButton);
      form.addEventListener('submit', async event => {
        event.preventDefault(); saveButton.disabled = true;
        try {
          await api(root + '/' + id + '/credential', {
            method: 'PUT',
            body: JSON.stringify({kind: kindSelect.value, value: valueInput.value}),
          });
          valueInput.value = '';
          say(title + ' credential saved.');
          await load();
        } catch (error) { if (isLoggedIn()) say(error.message); }
        finally { saveButton.disabled = false; }
      });
      card.append(form);

      if (record) {
        const clearButton = document.createElement('button'); clearButton.type = 'button'; clearButton.className = 'secondary';
        clearButton.textContent = 'Remove credential';
        clearButton.addEventListener('click', async () => {
          if (!window.confirm('Remove the stored ' + title + ' credential?')) return;
          clearButton.disabled = true;
          try { await api(root + '/' + id + '/credential', {method: 'DELETE'}); say(title + ' credential removed.'); await load(); }
          catch (error) { if (isLoggedIn()) say(error.message); }
          finally { clearButton.disabled = false; }
        });
        card.append(clearButton);
      }
      el('coding-agent-cards').append(card);
    }
  }
  async function load() {
    try {
      const records = await api(root + '/credentials');
      if (!isLoggedIn()) return;
      render(records); say('');
    } catch (error) { if (isLoggedIn()) say(error.message); }
  }
  return {load, reset};
}
