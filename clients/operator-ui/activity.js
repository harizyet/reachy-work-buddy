// Recent action receipts (Phase 39, ADR 0028): read-only, built by the
// assistant's own records rather than anything the model said. All text is
// rendered with textContent, never as HTML.
function createActivity({api, isLoggedIn}) {
  const el = id => document.getElementById(id);
  let loadToken = 0;
  const node = (tag, props = {}, ...children) => { const item = document.createElement(tag); Object.assign(item, props); item.append(...children); return item; };
  const when = iso => new Date(iso).toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'});
  const title = receipt => receipt.action_type.replace('.', ' · ').replace(/^./, c => c.toUpperCase());

  function render(receipts) {
    el('activity-list').replaceChildren(...receipts.map(receipt => {
      const detail = [when(receipt.at), receipt.source_channel, receipt.status === 'failed' ? `failed${receipt.failure_reason ? ': ' + receipt.failure_reason : ''}` : '',
        ...Object.entries(receipt.fields || {}).map(([key, value]) => `${key}: ${value}`)].filter(Boolean).join(' · ');
      return node('li', {className: 'planner-row'}, node('span', {className: 'planner-grow'},
        node('span', {className: receipt.status === 'failed' ? 'planner-done' : '', textContent: title(receipt)}),
        node('br'), node('span', {className: 'muted', textContent: detail})));
    }));
    el('activity-empty').hidden = receipts.length > 0;
  }

  async function load() {
    if (!isLoggedIn()) return;
    const token = ++loadToken;
    try {
      const receipts = await api('/planner/receipts');
      if (token !== loadToken || !isLoggedIn()) return;
      render(receipts); el('activity-status').textContent = '';
    } catch (error) { if (isLoggedIn() && token === loadToken) el('activity-status').textContent = error.message; }
  }

  el('activity-refresh').addEventListener('click', () => void load());
  function reset() { loadToken++; el('activity-list').replaceChildren(); el('activity-status').textContent = ''; el('activity-empty').hidden = false; }
  return {load, reset};
}
