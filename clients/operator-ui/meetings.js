// Phase 27.1 (docs/phase-27.md): basic Meetings UI — upload a recording,
// list uploaded meetings and their job status, cancel one still queued.
// Talks only to reachy-hub's /meetings proxy (see reachy_hub/operator.py);
// companion-core itself is closed to the browser.
function createMeetings({api, apiUploadForm, isLoggedIn}) {
  const el = id => document.getElementById(id);

  function statusLabel(status) {
    const labels = {
      uploaded: 'Queued', preprocessing: 'Preprocessing', transcribing: 'Waiting on transcription (not yet implemented)',
      diarizing: 'Diarizing', aligning: 'Aligning', analyzing: 'Analyzing', complete: 'Complete',
      failed: 'Failed', cancelled: 'Cancelled',
    };
    return labels[status] || status;
  }

  function renderList(meetingList) {
    const list = el('meeting-list');
    list.replaceChildren();
    for (const meeting of meetingList) {
      const item = document.createElement('li');
      const uploaded = new Date(meeting.created_at).toLocaleString();
      item.append(document.createTextNode(`${meeting.title} — ${statusLabel(meeting.status)} · uploaded ${uploaded} `));
      if (meeting.error_detail) {
        const detail = document.createElement('span');
        detail.className = 'muted';
        detail.textContent = `(${meeting.error_detail}) `;
        item.append(detail);
      }
      if (meeting.status === 'uploaded' || meeting.status === 'preprocessing') {
        const cancel = document.createElement('button');
        cancel.type = 'button'; cancel.className = 'secondary'; cancel.textContent = 'Cancel';
        cancel.addEventListener('click', () => void doCancel(meeting.id));
        item.append(cancel);
      }
      list.append(item);
    }
  }

  async function load() {
    if (!isLoggedIn()) return;
    try {
      const meetingList = await api('/meetings');
      el('meeting-list-status').textContent = meetingList.length ? '' : 'No meetings uploaded yet.';
      renderList(meetingList);
    } catch (error) {
      el('meeting-list-status').textContent = error.message;
    }
  }

  async function doCancel(meetingId) {
    try {
      await api(`/meetings/${meetingId}/cancel`, {method: 'POST'});
      await load();
    } catch (error) {
      el('meeting-list-status').textContent = error.message;
    }
  }

  el('meeting-upload-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter; if (button) button.disabled = true;
    el('meeting-upload-status').textContent = 'Uploading…';
    try {
      const file = el('meeting-audio').files[0];
      if (!file) throw new Error('Choose a recording to upload');
      const formData = new FormData();
      formData.set('title', el('meeting-title').value);
      formData.set('project_scope', el('meeting-project').value);
      formData.set('participants', el('meeting-participants').value);
      formData.set('context', el('meeting-context').value);
      formData.set('audio', file);
      await apiUploadForm('/meetings', formData);
      el('meeting-upload-status').textContent = 'Uploaded.';
      event.target.reset();
      await load();
    } catch (error) {
      el('meeting-upload-status').textContent = error.message;
    } finally {
      if (button) button.disabled = false;
    }
  });

  function reset() {
    el('meeting-upload-form').reset();
    el('meeting-upload-status').textContent = '';
    el('meeting-list-status').textContent = '';
    el('meeting-list').replaceChildren();
  }

  return {load, reset};
}
