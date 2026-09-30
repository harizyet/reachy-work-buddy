// Phase 27.1/27.2/27.3 (docs/phase-27.md): Meetings UI — upload or record a
// meeting, list uploaded meetings and their job status, cancel one still in
// progress, and view a meeting's raw transcript/diarization output once its
// sidecars have produced it. Talks only to reachy-hub's /meetings proxy (see
// reachy_hub/operator.py); companion-core itself is closed to the browser.
//
// There is no structured meeting-minutes/decisions/actions view here —
// 27.4 (alignment) and 27.6 (analysis) are not implemented (see
// docs/phase-27.md's Status section), so this shows the two sidecars' raw
// segment output side by side rather than a merged, speaker-attributed
// transcript or fabricated "minutes". Recording captures one clip in the
// browser and uploads it through the exact same /meetings endpoint as a
// file upload (phase-27.md 27.20: "This must feed exactly the same backend
// pipeline as uploaded recordings").
function createMeetings({api, apiUploadForm, isLoggedIn}) {
  const el = id => document.getElementById(id);

  const STATUS_LABELS = {
    uploaded: 'Queued', preprocessing: 'Preprocessing', transcribing: 'Transcribing',
    diarizing: 'Diarizing', aligning: 'Aligning (waiting on 27.4)', analyzing: 'Analyzing',
    complete: 'Complete', failed: 'Failed', cancelled: 'Cancelled',
  };
  function statusLabel(status) { return STATUS_LABELS[status] || status; }

  function formatTimestamp(seconds) {
    if (seconds === null || seconds === undefined) return '--:--';
    const total = Math.max(0, Math.round(seconds));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  // --- recording ------------------------------------------------------

  const canRecord = Boolean(window.MediaRecorder && navigator.mediaDevices?.getUserMedia);
  const RECORD_MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
  let recordMimeType = null;
  if (canRecord) {
    recordMimeType = RECORD_MIME_CANDIDATES.find(type => MediaRecorder.isTypeSupported(type)) || null;
  }
  let mediaStream = null;
  let recorder = null;
  let recordedChunks = [];
  let recordedBlob = null;
  let recordingStartedAt = null;
  let recordingTimer = null;

  function recordingExtension() {
    if (!recordMimeType) return 'webm';
    if (recordMimeType.startsWith('audio/ogg')) return 'opus';
    return 'webm';
  }

  function updateRecordingElapsed() {
    if (!recordingStartedAt) return;
    const seconds = (Date.now() - recordingStartedAt) / 1000;
    el('meeting-record-status').textContent = `Recording… ${formatTimestamp(seconds)}`;
  }

  function setRecordedClip(blob) {
    recordedBlob = blob;
    el('meeting-audio').value = '';
    el('meeting-audio').disabled = Boolean(blob);
    if (blob) {
      el('meeting-record-status').textContent = `Recorded clip ready (${formatTimestamp(blob.__durationSeconds || 0)}).`;
      el('meeting-record-discard').hidden = false;
    } else {
      el('meeting-record-status').textContent = '';
      el('meeting-record-discard').hidden = true;
    }
  }

  async function startRecording() {
    if (!canRecord) return;
    setRecordedClip(null);
    el('meeting-record-start').disabled = true;
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({audio: true});
    } catch (error) {
      el('meeting-record-status').textContent = `Could not access the microphone: ${error.message}`;
      el('meeting-record-start').disabled = false;
      return;
    }
    recordedChunks = [];
    recorder = recordMimeType ? new MediaRecorder(mediaStream, {mimeType: recordMimeType}) : new MediaRecorder(mediaStream);
    recorder.addEventListener('dataavailable', event => { if (event.data.size > 0) recordedChunks.push(event.data); });
    recorder.addEventListener('stop', () => {
      const blob = new Blob(recordedChunks, {type: recorder.mimeType || 'audio/webm'});
      blob.__durationSeconds = recordingStartedAt ? (Date.now() - recordingStartedAt) / 1000 : 0;
      for (const track of mediaStream.getTracks()) track.stop();
      mediaStream = null;
      setRecordedClip(blob);
    });
    recorder.start();
    recordingStartedAt = Date.now();
    recordingTimer = setInterval(updateRecordingElapsed, 500);
    updateRecordingElapsed();
    el('meeting-record-stop').hidden = false;
    el('meeting-record-start').hidden = true;
  }

  function stopRecording() {
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    clearInterval(recordingTimer);
    recordingTimer = null;
    recordingStartedAt = null;
    el('meeting-record-stop').hidden = true;
    el('meeting-record-start').hidden = false;
    el('meeting-record-start').disabled = false;
  }

  function discardRecording() {
    setRecordedClip(null);
  }

  if (canRecord) {
    el('meeting-record-start').addEventListener('click', () => void startRecording());
    el('meeting-record-stop').addEventListener('click', stopRecording);
    el('meeting-record-discard').addEventListener('click', discardRecording);
  } else {
    el('meeting-record-controls').hidden = true;
    el('meeting-record-status').textContent = 'Recording from the browser is not supported here — upload a file instead.';
  }

  // --- list + detail ----------------------------------------------------

  let meetingsById = new Map();

  function renderList(meetingList) {
    meetingsById = new Map(meetingList.map(meeting => [meeting.id, meeting]));
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
      const view = document.createElement('button');
      view.type = 'button'; view.className = 'secondary'; view.textContent = 'View';
      view.addEventListener('click', () => void showDetail(meeting.id));
      item.append(view);
      const terminal = ['complete', 'failed', 'cancelled'];
      if (!terminal.includes(meeting.status)) {
        const cancel = document.createElement('button');
        cancel.type = 'button'; cancel.className = 'secondary'; cancel.textContent = 'Cancel';
        cancel.addEventListener('click', () => void doCancel(meeting.id));
        item.append(cancel);
      }
      list.append(item);
    }
  }

  function renderSegments(container, segments, {kind}) {
    container.replaceChildren();
    if (!segments || !segments.length) {
      const empty = document.createElement('p');
      empty.className = 'muted';
      empty.textContent = kind === 'transcript' ? 'No transcript yet.' : 'No speaker segments yet.';
      container.append(empty);
      return;
    }
    const list = document.createElement('ul');
    list.className = 'sample-list';
    for (const segment of segments) {
      const item = document.createElement('li');
      const stamp = `${formatTimestamp(segment.start)}–${formatTimestamp(segment.end)}`;
      item.textContent = kind === 'transcript'
        ? `${stamp}  ${segment.text || ''}`
        : `${stamp}  ${segment.speaker || 'unknown speaker'}`;
      list.append(item);
    }
    container.append(list);
  }

  async function showDetail(meetingId) {
    el('meeting-detail').hidden = false;
    el('meeting-detail-status').textContent = 'Loading…';
    try {
      const meeting = await api(`/meetings/${meetingId}`);
      meetingsById.set(meetingId, meeting);
      el('meeting-detail-title').textContent = meeting.title;
      const parts = [`Status: ${statusLabel(meeting.status)}`];
      if (meeting.project_scope) parts.push(`Project: ${meeting.project_scope}`);
      if (meeting.participants?.length) parts.push(`Participants: ${meeting.participants.join(', ')}`);
      if (meeting.duration_seconds) parts.push(`Duration: ${formatTimestamp(meeting.duration_seconds)}`);
      el('meeting-detail-meta').textContent = parts.join(' · ');
      el('meeting-detail-context').textContent = meeting.context || '';
      el('meeting-detail-status').textContent = meeting.error_detail ? `Error: ${meeting.error_detail}` : '';
      renderSegments(el('meeting-detail-transcript'), meeting.transcript_segments, {kind: 'transcript'});
      renderSegments(el('meeting-detail-diarization'), meeting.diarization_segments, {kind: 'diarization'});
    } catch (error) {
      el('meeting-detail-status').textContent = error.message;
    }
  }

  el('meeting-detail-close').addEventListener('click', () => { el('meeting-detail').hidden = true; });

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
      const source = recordedBlob || file;
      if (!source) throw new Error('Record a clip or choose a recording to upload');
      const formData = new FormData();
      formData.set('title', el('meeting-title').value);
      formData.set('project_scope', el('meeting-project').value);
      formData.set('participants', el('meeting-participants').value);
      formData.set('context', el('meeting-context').value);
      const filename = recordedBlob ? `recording.${recordingExtension()}` : file.name;
      formData.set('audio', source, filename);
      await apiUploadForm('/meetings', formData);
      el('meeting-upload-status').textContent = 'Uploaded.';
      event.target.reset();
      setRecordedClip(null);
      await load();
    } catch (error) {
      el('meeting-upload-status').textContent = error.message;
    } finally {
      if (button) button.disabled = false;
    }
  });

  function reset() {
    stopRecording();
    setRecordedClip(null);
    el('meeting-upload-form').reset();
    el('meeting-upload-status').textContent = '';
    el('meeting-list-status').textContent = '';
    el('meeting-list').replaceChildren();
    el('meeting-detail').hidden = true;
  }

  return {load, reset};
}
