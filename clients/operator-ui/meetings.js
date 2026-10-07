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
function createMeetings({api, apiUploadForm, isLoggedIn, onUseAsContext = () => {}}) {
  const el = id => document.getElementById(id);

  const STATUS_LABELS = {
    uploaded: 'Queued', preprocessing: 'Preparing audio', transcribing: 'Transcribing',
    diarizing: 'Identifying speakers', aligning: 'Ready', analyzing: 'Analyzing',
    complete: 'Complete', failed: 'Failed', cancelled: 'Cancelled',
  };
  function statusLabel(status) { return STATUS_LABELS[status] || status; }

  function statusDescription(meeting) {
    if (meeting.status === 'aligning') return 'Transcript and speakers are ready.';
    if (meeting.status === 'failed') return 'Processing failed. Open details for the technical error.';
    if (meeting.status === 'cancelled') return 'Processing was cancelled.';
    return '';
  }

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
  let selectedMeeting = null;
  let detailVersion = 0;

  // Phase 27.4 follow-up: stretches where the phone captured no audio (exact silence), found by the server.
  function silentSeconds(meeting) { return meeting.audio_gaps?.seconds || 0; }
  function silentSummary(meeting) {
    const seconds = Math.round(silentSeconds(meeting));
    return `${formatTimestamp(seconds)} of this recording has no audio — the phone stopped capturing sound (for example when it locked or another app used the microphone). Lines marked ⚠ may be missing or unreliable.`;
  }
  function warningIcon(label) {
    const icon = document.createElement('span');
    icon.className = 'gap-warning'; icon.textContent = '⚠'; icon.title = label;
    icon.setAttribute('role', 'img'); icon.setAttribute('aria-label', label);
    return icon;
  }

  function renderList(meetingList) {
    meetingsById = new Map(meetingList.map(meeting => [meeting.id, meeting]));
    const failedCount = meetingList.filter(m => m.status === 'failed' || m.status === 'cancelled').length;
    el('meeting-clear-failed').hidden = failedCount === 0;
    el('meeting-clear-failed').textContent = `Delete failed and cancelled (${failedCount})`;
    const list = el('meeting-list');
    list.replaceChildren();
    const query = el('meeting-search').value.trim().toLowerCase();
    for (const meeting of meetingList.filter(m => m.title.toLowerCase().includes(query))) {
      const item = document.createElement('li');
      item.className = 'meeting-item';
      item.classList.toggle('selected', meeting.id === selectedMeeting);
      const heading = document.createElement('div');
      heading.className = 'meeting-heading';
      const title = document.createElement('strong');
      title.textContent = meeting.title;
      const status = document.createElement('span');
      status.className = 'meeting-status';
      status.textContent = statusLabel(meeting.status);
      heading.append(title, status);
      if (silentSeconds(meeting) > 0) title.append(' ', warningIcon('Part of this recording has no audio'));
      const uploaded = document.createElement('p');
      uploaded.className = 'muted';
      uploaded.textContent = `Uploaded ${new Date(meeting.created_at).toLocaleString()}`;
      item.append(heading, uploaded);
      const actions = document.createElement('div');
      actions.className = 'meeting-actions';
      const view = document.createElement('button');
      view.setAttribute('aria-pressed', String(meeting.id === selectedMeeting));
      view.type = 'button'; view.className = 'secondary'; view.textContent = 'View details';
      view.addEventListener('click', () => void showDetail(meeting.id));
      actions.append(view);
      if (DELETABLE.includes(meeting.status)) {
        const remove = document.createElement('button');
        remove.type = 'button'; remove.className = 'secondary'; remove.textContent = 'Delete';
        remove.setAttribute('aria-label', `Delete ${meeting.title}`);
        remove.addEventListener('click', () => void deleteMeeting(meeting));
        actions.append(remove);
      }
      const terminal = ['complete', 'failed', 'cancelled'];
      if (!terminal.includes(meeting.status)) {
        const cancel = document.createElement('button');
        cancel.type = 'button'; cancel.className = 'secondary'; cancel.textContent = 'Cancel processing';
        cancel.addEventListener('click', () => void doCancel(meeting.id));
        actions.append(cancel);
      }
      item.append(actions);
      list.append(item);
    }
  }

  // --- deleting, summaries and minutes (Phase 43) ----------------------------------------------------------
  const DELETABLE = ['complete', 'failed', 'cancelled', 'aligning'];  // nothing is running for the meeting in these states
  const READY = ['aligning', 'analyzing', 'complete'];
  let section = 'transcript';
  let generating = null;

  function confirmAction(title, text, label) {
    return new Promise(resolve => {
      const dialog = el('confirm-dialog');
      el('confirm-title').textContent = title; el('confirm-text').textContent = text; el('confirm-ok').textContent = label;
      const done = value => { el('confirm-ok').onclick = null; el('confirm-cancel').onclick = null; dialog.close(); resolve(value); };
      el('confirm-ok').onclick = () => done(true); el('confirm-cancel').onclick = () => done(false);
      dialog.addEventListener('cancel', () => done(false), {once: true});
      dialog.showModal();
    });
  }

  async function deleteMeeting(meeting) {
    const ok = await confirmAction('Delete this meeting?', `\u201c${meeting.title}\u201d will be removed with its recording, transcript, speaker names, corrections, summary and minutes. This cannot be undone.`, 'Delete');
    if (!ok) return;
    try {
      await api(`/meetings/${meeting.id}`, {method: 'DELETE'});
      if (selectedMeeting === meeting.id) newMeeting();
      await load();
    } catch (error) { el('meeting-list-status').textContent = error.message; }
  }

  async function clearFailed() {
    const failed = [...meetingsById.values()].filter(m => m.status === 'failed' || m.status === 'cancelled');
    if (!failed.length) return;
    const ok = await confirmAction('Delete failed and cancelled meetings?', `This removes ${failed.length} meeting${failed.length === 1 ? '' : 's'} and ${failed.length === 1 ? 'its' : 'their'} recording${failed.length === 1 ? '' : 's'}. It cannot be undone.`, 'Delete');
    if (!ok) return;
    try { for (const meeting of failed) await api(`/meetings/${meeting.id}`, {method: 'DELETE'}); await load(); }
    catch (error) { el('meeting-list-status').textContent = error.message; }
  }
  el('meeting-clear-failed').addEventListener('click', () => void clearFailed());

  const tierLabel = {local: 'the local model', deep: 'the larger local model', cloud: 'the cloud model'};
  function renderOutput() {
    const kind = section;
    const meeting = meetingsById.get(selectedMeeting);
    const showOutput = kind === 'summary' || kind === 'minutes';
    el('meeting-output').hidden = !showOutput;
    el('meeting-transcript-section').hidden = showOutput;
    for (const name of ['summary', 'minutes', 'transcript']) el(`meeting-tab-${name}`).setAttribute('aria-pressed', String(name === section));
    if (!showOutput || !meeting) return;
    const output = meeting[kind];
    el('meeting-output-text').textContent = generating === kind ? '' : (output ? output.text : '');
    el('meeting-output-status').textContent = generating === kind ? `Writing the ${kind} with the local model\u2026` : output ? '' : `No ${kind} yet.`;
    el('meeting-output-meta').textContent = output && generating !== kind
      ? `Written by ${tierLabel[output.tier] || output.tier}${output.generated_at ? ' \u00b7 ' + new Date(output.generated_at).toLocaleString() : ''}. A model wrote this from a speech-to-text transcript, so check it; if it is not accurate enough, rerun it on a stronger model.` : '';
    el('meeting-output-run').textContent = output ? 'Rerun' : `Write the ${kind}`;
    el('meeting-output-run').disabled = generating !== null;
    el('meeting-output-clear').hidden = !output;
  }

  async function runOutput(kind, model) {
    if (model === 'deep') { void askDeep(kind); return; }
    generating = kind; renderOutput();
    try {
      const updated = await api(`/meetings/${selectedMeeting}/outputs/${kind}`, {method: 'POST', body: JSON.stringify({model})});
      meetingsById.set(selectedMeeting, updated);
    } catch (error) { el('meeting-output-status').textContent = error.message; }
    finally { generating = null; renderOutput(); }
  }

  async function setSection(next) {
    section = next; renderOutput();
    const meeting = meetingsById.get(selectedMeeting);
    if ((next === 'summary' || next === 'minutes') && meeting && !meeting[next] && generating === null) await runOutput(next, 'local');
  }
  for (const name of ['summary', 'minutes', 'transcript']) el(`meeting-tab-${name}`).addEventListener('click', () => void setSection(name));
  el('meeting-output-run').addEventListener('click', () => void runOutput(section, el('meeting-output-model').value));
  el('meeting-output-clear').addEventListener('click', async () => {
    try { meetingsById.set(selectedMeeting, await api(`/meetings/${selectedMeeting}/outputs/${section}`, {method: 'DELETE'})); renderOutput(); }
    catch (error) { el('meeting-output-status').textContent = error.message; }
  });
  el('meeting-use-context').addEventListener('click', () => { const m = meetingsById.get(selectedMeeting); if (m) onUseAsContext({id: m.id, title: m.title}); });
  el('meeting-delete').addEventListener('click', () => { const m = meetingsById.get(selectedMeeting); if (m) void deleteMeeting(m); });

  // --- suggested corrections and the deep local review ----------------------------------------------------
  // Meeting speech goes to the local model unless the owner picks the cloud for one request. "Deep local" runs on
  // the larger local model, which unloads Reachy's standard model: it needs an explicit warning, follows the job
  // until Reachy is back, and (when allowed) raises a browser notification at the end. All text is set with
  // textContent, never as HTML.
  let suggestions = [];
  let deepFollow = null;
  let deepTask = 'corrections';
  let reloadedJob = null;
  const deepMinutes = info => Math.max(1, Math.round((info?.eta_seconds || 330) / 60));

  function renderSuggestions() {
    const list = el('meeting-suggestions');
    const groups = new Map();
    for (const s of suggestions) {
      const key = `${s.original}\u0000${s.suggested}`;
      if (!groups.has(key)) groups.set(key, {...s, places: 0});
      groups.get(key).places += 1;
    }
    list.replaceChildren(...[...groups.values()].map(group => {
      const item = document.createElement('li');
      item.className = 'planner-row';
      const text = document.createElement('span');
      text.className = 'planner-grow';
      const heading = document.createElement('strong');
      heading.textContent = `${group.original} \u2192 ${group.suggested}`;
      const note = document.createElement('div');
      note.className = 'suggestion-conf';
      note.textContent = {high: 'High confidence: same letters as your term', likely: 'Matches your term: judged by the model, check it'}[group.confidence]
        || 'Model guess: check before applying';
      const reason = document.createElement('div');
      reason.textContent = group.reason || '';
      text.append(heading, note, reason);
      const apply = document.createElement('button');
      apply.type = 'button'; apply.textContent = group.places > 1 ? `Change all ${group.places}` : 'Change';
      apply.addEventListener('click', async () => {
        try {
          const result = await api(`/meetings/${selectedMeeting}/corrections/replace`, {method: 'POST', body: JSON.stringify({find: group.original, replace: group.suggested})});
          suggestions = suggestions.filter(s => !(s.original === group.original && s.suggested === group.suggested));
          el('meeting-suggest-status').textContent = `Changed ${result.replaced_segments} place${result.replaced_segments === 1 ? '' : 's'}.`;
          await showDetail(selectedMeeting, {keepSuggestions: true});
        } catch (error) { el('meeting-suggest-status').textContent = error.message; }
      });
      const dismiss = document.createElement('button');
      dismiss.type = 'button'; dismiss.className = 'secondary'; dismiss.textContent = 'Dismiss';
      dismiss.addEventListener('click', () => { suggestions = suggestions.filter(s => !(s.original === group.original && s.suggested === group.suggested)); renderSuggestions(); });
      item.append(text, apply, dismiss);
      return item;
    }));
  }

  function showResult(result) {
    suggestions = result.suggestions || [];
    const used = result.terms_used || 0;
    el('meeting-suggest-status').textContent = result.truncated ? 'Some parts of the meeting could not be checked. Run again to retry.'
      : suggestions.length ? `Checked against ${used} term${used === 1 ? '' : 's'}.`
      : used ? `No likely mistakes found (checked against ${used} terms).` : 'No likely mistakes found. Add key terms to catch more.';
    renderSuggestions();
  }

  function setBanner(job) {
    const unavailable = Boolean(job) && (!['done', 'failed'].includes(job.status) || job.reachy_unavailable);
    el('deep-banner').hidden = !unavailable;
    el('deep-banner-stage').textContent = unavailable ? (job.stage || '') : '';
    el('meeting-suggest-go').disabled = unavailable;
  }

  function followDeep(jobId) {
    clearTimeout(deepFollow);
    const poll = async () => {
      if (!isLoggedIn()) return;
      try {
        const job = await api(`/deep-review/${jobId}`);
        setBanner(job);
        if (job.result && selectedMeeting === job.meeting_id) {
          if (job.task === 'corrections' || !job.task) { if (!suggestions.length) showResult(job.result); }
          else if (reloadedJob !== job.id) { reloadedJob = job.id; void showDetail(selectedMeeting, {keepSuggestions: true}); }
        }
        if (job.status === 'done' || job.status === 'failed') {
          const title = job.meeting_title || 'your meeting';
          const what = {summary: 'deep summary', minutes: 'deep minutes'}[job.task] || 'deep review';
          const text = !job.reachy_online ? `Reachy's standard model could not be reloaded after the ${what} of "${title}". It needs manual recovery.`
            : job.status === 'failed' ? `The ${what} of "${title}" did not complete (${job.error || 'unknown error'}), but Reachy is back online.`
            : `The ${what} of "${title}" is complete. Reachy is back online.`;
          el('notice').textContent = text;
          if ('Notification' in window && Notification.permission === 'granted') new Notification(job.reachy_online ? 'Reachy is available again' : 'Reachy needs attention', {body: text});
          return;
        }
      } catch (error) { /* keep trying: the connection may be briefly down */ }
      deepFollow = setTimeout(poll, 4000);
    };
    void poll();
  }

  async function startDeepReview() {
    el('deep-warning').close();
    if ('Notification' in window && Notification.permission === 'default') { try { await Notification.requestPermission(); } catch (error) { /* optional */ } }
    try {
      const url = deepTask === 'corrections' ? `/meetings/${selectedMeeting}/corrections/deep-review` : `/meetings/${selectedMeeting}/outputs/${deepTask}/deep`;
      const job = await api(url, {method: 'POST'});
      const note = `Deep ${deepTask === 'corrections' ? 'review' : deepTask} started. Reachy is unavailable until it finishes.`;
      if (deepTask === 'corrections') { suggestions = []; renderSuggestions(); el('meeting-suggest-status').textContent = note; } else el('meeting-output-status').textContent = note;
      setBanner(job); followDeep(job.id);
    } catch (error) { (deepTask === 'corrections' ? el('meeting-suggest-status') : el('meeting-output-status')).textContent = error.message; }
  }

  // The same warning and job for every deep task: corrections, summary or minutes.
  async function askDeep(task) {
    deepTask = task;
    const status = task === 'corrections' ? el('meeting-suggest-status') : el('meeting-output-status');
    let info = null;
    try { info = await api('/deep-review/info'); } catch (error) { status.textContent = error.message; return; }
    if (!info.available) { status.textContent = `Deep local is unavailable: ${info.reason || 'not ready'}.`; return; }
    el('deep-warning-text').textContent = deepWarning(info);
    el('deep-warning').showModal();
  }

  function deepWarning(info) {
    return `Reachy will be unavailable for about ${deepMinutes(info)} minutes. The larger model takes over the GPU: it loads (about 2 minutes), works on this meeting, then Reachy's standard model reloads (about 1.5 minutes). Reachy's local replies will not work until then. You will get a notification here and a Telegram message when Reachy is back online.`;
  }

  el('meeting-suggest-go').addEventListener('click', async () => {
    const choice = el('meeting-suggest-model').value;
    if (choice === 'deep') {
      void askDeep('corrections'); return;
    }
    el('meeting-suggest-status').textContent = 'Checking…';
    el('meeting-suggest-go').disabled = true;
    try {
      showResult(await api(`/meetings/${selectedMeeting}/corrections/suggest`, {method: 'POST', body: JSON.stringify({model: choice})}));
    } catch (error) { el('meeting-suggest-status').textContent = error.message; }
    finally { el('meeting-suggest-go').disabled = false; }
  });
  el('deep-warning-cancel').addEventListener('click', () => el('deep-warning').close());
  el('deep-warning-start').addEventListener('click', () => void startDeepReview());

  async function resumeDeep() {
    try {
      const job = await api('/deep-review/current');
      if (job && !['done', 'failed'].includes(job.status)) { setBanner(job); followDeep(job.id); }
    } catch (error) { /* the banner simply does not show */ }
  }

  // The stored alignment (Phase 27.4) gives each transcript line its speaker; the owner's name wins over "Speaker N".
  function speakerName(meeting, label) {
    const named = meeting.speaker_names?.[label];
    if (named) return named;
    const match = /^SPEAKER_(\d+)$/.exec(label);
    return match ? `Speaker ${Number(match[1]) + 1}` : label;
  }

  function renameSpeaker(meeting, label) {
    const dialog = el('speaker-dialog');
    el('speaker-dialog-title').textContent = `Who is ${speakerName(meeting, label)}?`;
    el('speaker-dialog-name').value = meeting.speaker_names?.[label] || '';
    el('speaker-dialog-clear').hidden = !meeting.speaker_names?.[label];
    const save = async name => {
      dialog.close();
      try {
        const updated = await api(`/meetings/${meeting.id}/speakers`, {method: 'PUT', body: JSON.stringify({names: {[label]: name}})});
        meetingsById.set(meeting.id, updated);
        await showDetail(meeting.id, {keepSuggestions: true});
      } catch (error) { el('meeting-detail-status').textContent = error.message; }
    };
    el('speaker-dialog-save').onclick = () => { const name = el('speaker-dialog-name').value.trim(); if (name) void save(name); };
    el('speaker-dialog-clear').onclick = () => void save('');
    el('speaker-dialog-cancel').onclick = () => dialog.close();
    dialog.showModal();
  }

  function playFrom(seconds) {
    const audio = el('meeting-player');
    audio.currentTime = Math.max(0, seconds || 0);
    void audio.play().catch(() => { /* Playback needs a user gesture on some browsers; the controls still work. */ });
  }

  function editLine(meeting, index) {
    const segment = meeting.transcript_segments[index];
    const current = meeting.transcript_corrections?.[String(index)];
    const dialog = el('line-dialog');
    el('line-dialog-title').textContent = `Edit line at ${formatTimestamp(segment.start)}`;
    el('line-dialog-original').textContent = current !== undefined ? `Original: ${segment.text || ''}` : '';
    el('line-dialog-text').value = current ?? (segment.text || '');
    el('line-dialog-revert').hidden = current === undefined;
    const done = async request => {
      dialog.close();
      try {
        const updated = await api(`/meetings/${meeting.id}/corrections/${index}`, request);
        meetingsById.set(meeting.id, updated);
        await showDetail(meeting.id, {keepSuggestions: true});
      } catch (error) { el('meeting-detail-status').textContent = error.message; }
    };
    el('line-dialog-save').onclick = () => {
      const text = el('line-dialog-text').value.trim();
      if (text) void done({method: 'PUT', body: JSON.stringify({text})});
    };
    el('line-dialog-revert').onclick = () => void done({method: 'DELETE'});
    el('line-dialog-cancel').onclick = () => dialog.close();
    dialog.showModal();
  }

  el('meeting-player').addEventListener('timeupdate', () => {
    const meeting = meetingsById.get(selectedMeeting);
    const segments = meeting?.transcript_segments;
    if (!segments) return;
    const now = el('meeting-player').currentTime;
    const active = segments.findIndex(s => now >= s.start && now < s.end);
    for (const item of el('meeting-detail-transcript').querySelectorAll('li')) {
      item.classList.toggle('playing', Number(item.dataset.index) === active);
    }
  });

  function renderSegments(container, segments, {kind, corrections, meeting}) {
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
      const index = segments.indexOf(segment);
      const corrected = kind === 'transcript' && corrections ? corrections[String(index)] : undefined;
      if (kind === 'transcript') {
        if (meeting?.audio_gaps?.segments?.includes(index)) item.append(warningIcon('No audio was recorded for most of this line'), ' ');
        const aligned = meeting?.aligned_segments;
        const label = aligned && aligned.length === segments.length ? aligned[index]?.speaker : null;
        const previous = aligned && aligned.length === segments.length && index > 0 ? aligned[index - 1]?.speaker : null;
        if (label && label !== previous) {
          const chip = document.createElement('button');
          chip.type = 'button'; chip.className = 'secondary speaker-chip';
          chip.textContent = speakerName(meeting, label);
          chip.setAttribute('aria-label', `Rename ${speakerName(meeting, label)}`);
          chip.addEventListener('click', () => renameSpeaker(meeting, label));
          item.append(chip, ' ');
        }
        item.dataset.index = String(index);
        const line = document.createElement('span');
        line.className = 'line-text'; line.tabIndex = 0; line.setAttribute('role', 'button');
        line.title = 'Play from here';
        line.textContent = `${stamp}  ${corrected ?? (segment.text || '')}${corrected !== undefined ? '  (edited)' : ''}`;
        line.addEventListener('click', () => playFrom(segment.start));
        line.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); playFrom(segment.start); } });
        const edit = document.createElement('button');
        edit.type = 'button'; edit.className = 'secondary line-edit'; edit.textContent = 'Edit';
        edit.setAttribute('aria-label', `Edit line at ${formatTimestamp(segment.start)}`);
        edit.addEventListener('click', () => editLine(meeting, index));
        item.append(line, ' ', edit);
      } else item.textContent = `${stamp}  ${segment.speaker || 'unknown speaker'}`;
      list.append(item);
    }
    container.append(list);
  }

  async function showDetail(meetingId, {keepSuggestions = false} = {}) {
    if (recorder?.state === 'recording') stopRecording();
    const version = ++detailVersion;
    selectedMeeting = meetingId;
    renderList([...meetingsById.values()]);
    el('meeting-create').hidden = true;
    el('meeting-detail').hidden = false;
    if (!keepSuggestions) { suggestions = []; el('meeting-suggestions').replaceChildren(); el('meeting-suggest-status').textContent = ''; section = 'transcript'; }
    el('meeting-detail-title').textContent = '';
    el('meeting-detail-meta').textContent = '';
    el('meeting-detail-context').textContent = '';
    el('meeting-detail-gaps').hidden = true;
    el('meeting-detail-transcript').replaceChildren();
    el('meeting-detail-diarization').replaceChildren();
    el('meeting-detail-error').hidden = true;
    el('meeting-detail-error').open = false;
    el('meeting-detail-error-text').textContent = '';
    el('meeting-detail-status').textContent = 'Loading…';
    try {
      const meeting = await api(`/meetings/${meetingId}`);
      if (version !== detailVersion || !isLoggedIn()) return;
      meetingsById.set(meetingId, meeting);
      el('meeting-detail-title').textContent = meeting.title;
      const audio = el('meeting-player');
      if (audio.dataset.meeting !== meetingId) { audio.pause(); audio.src = `${base}/meetings/${encodeURIComponent(meetingId)}/audio`; audio.dataset.meeting = meetingId; }
      const parts = [`Status: ${statusLabel(meeting.status)}`];
      if (meeting.project_scope) parts.push(`Project: ${meeting.project_scope}`);
      if (meeting.participants?.length) parts.push(`Participants: ${meeting.participants.join(', ')}`);
      if (meeting.duration_seconds) parts.push(`Duration: ${formatTimestamp(meeting.duration_seconds)}`);
      el('meeting-detail-meta').textContent = parts.join(' · ');
      el('meeting-detail-context').textContent = meeting.context || '';
      el('meeting-detail-gaps').hidden = silentSeconds(meeting) <= 0;
      el('meeting-detail-gaps').textContent = silentSeconds(meeting) > 0 ? `⚠ ${silentSummary(meeting)}` : '';
      el('meeting-detail-status').textContent = statusDescription(meeting);
      el('meeting-detail-error').hidden = !meeting.error_detail;
      el('meeting-detail-error-text').textContent = meeting.error_detail || '';
      const ready = Boolean(meeting.transcript_segments && meeting.transcript_segments.length) && READY.includes(meeting.status);
      el('meeting-toolbar').hidden = !ready;
      el('meeting-delete').hidden = !DELETABLE.includes(meeting.status);
      el('meeting-suggest').hidden = !(meeting.transcript_segments && meeting.transcript_segments.length);
      if (!ready) section = 'transcript';
      renderOutput();
      renderSegments(el('meeting-detail-transcript'), meeting.transcript_segments, {kind: 'transcript', corrections: meeting.transcript_corrections, meeting});
      renderSegments(el('meeting-detail-diarization'), meeting.diarization_segments, {kind: 'diarization'});
    } catch (error) {
      if (version === detailVersion) el('meeting-detail-status').textContent = error.message;
    }
  }

  function newMeeting() {
    detailVersion += 1; selectedMeeting = null;
    el('meeting-player').pause();
    el('meeting-detail').hidden = true; el('meeting-create').hidden = false;
    renderList([...meetingsById.values()]);
  }
  el('meeting-detail-close').addEventListener('click', newMeeting);
  el('meeting-new').addEventListener('click', newMeeting);
  el('meeting-refresh').addEventListener('click', async () => {
    await load();
    if (selectedMeeting) await showDetail(selectedMeeting);
  });
  el('meeting-search').addEventListener('input', () => renderList([...meetingsById.values()]));

  async function load() {
    if (!isLoggedIn()) return;
    void resumeDeep();
    try {
      const meetingList = await api('/meetings');
      if (!isLoggedIn()) return;
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
      if (selectedMeeting === meetingId) await showDetail(meetingId);
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
    clearTimeout(deepFollow); suggestions = []; setBanner(null); section = 'transcript'; generating = null;
    stopRecording();
    setRecordedClip(null);
    el('meeting-upload-form').reset();
    el('meeting-upload-status').textContent = '';
    el('meeting-list-status').textContent = '';
    meetingsById.clear(); el('meeting-search').value = '';
    newMeeting();
  }

  return {load, reset, resumeDeep};
}
