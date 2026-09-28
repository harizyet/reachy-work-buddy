// Phase 25a.2/25b.3 (docs/phase-25.md "Enrollment portal"): captures raw
// voice/face samples toward a future benchmark and enrollment dataset. No
// recognition model reads these yet — see reachy_hub/owner_recognition.py.
// Microphone/camera streams and captured blobs never touch localStorage;
// each capture is uploaded and then discarded from the browser.
function createOwnerRecognition({api, apiUpload, isLoggedIn}) {
  const el = id => document.getElementById(id);
  const root = '/owner-recognition';
  let generation = 0;
  let reauthenticated = false;
  let voiceStream = null, voiceRecorder = null, voiceChunks = [];
  let faceStream = null;

  function say(id, text) { el(id).textContent = text; }

  async function run(statusId, action, buttonNode) {
    if (buttonNode) buttonNode.disabled = true;
    try { await action(); } catch (error) { if (isLoggedIn()) say(statusId, error.message); }
    finally { if (buttonNode && isLoggedIn()) buttonNode.disabled = false; }
  }

  function renderSampleList(listId, samples, kind) {
    const list = el(listId);
    list.replaceChildren();
    for (const sample of samples) {
      const item = document.createElement('li');
      const captured = new Date(sample.captured_at).toLocaleString();
      const sizeKb = Math.max(1, Math.round(sample.size_bytes / 1024));
      item.append(document.createTextNode(`${captured} · ${sizeKb} KB `));
      const remove = document.createElement('button');
      remove.type = 'button'; remove.className = 'secondary'; remove.textContent = 'Delete';
      remove.disabled = !reauthenticated;
      remove.addEventListener('click', () => run(`${kind}-sample-status`, async () => {
        await api(`${root}/${kind}/samples/${encodeURIComponent(sample.sample_id)}`, {method: 'DELETE'});
        await load();
      }, remove));
      item.append(remove);
      list.append(item);
    }
    if (!samples.length) {
      const empty = document.createElement('li'); empty.className = 'muted'; empty.textContent = 'No samples recorded yet.';
      list.append(empty);
    }
  }

  function render(status) {
    reauthenticated = status.reauthenticated;
    say('owner-recognition-reauth-status', reauthenticated
      ? `Password confirmed — expires in about ${Math.ceil(status.reauth_expires_in_seconds / 60)} minute(s).`
      : 'Confirm your password to record or delete samples.');
    renderSampleList('voice-sample-list', status.voice_samples, 'voice');
    renderSampleList('face-sample-list', status.face_samples, 'face');
    el('voice-sample-delete-all').disabled = !reauthenticated || !status.voice_samples.length;
    el('face-sample-delete-all').disabled = !reauthenticated || !status.face_samples.length;
    el('voice-sample-record').disabled = !reauthenticated;
    el('face-sample-start').disabled = !reauthenticated;
  }

  async function load() {
    const ticket = ++generation;
    await run('owner-recognition-reauth-status', async () => {
      const status = await api(`${root}/status`);
      if (!isLoggedIn() || ticket !== generation) return;
      render(status);
    });
  }

  el('owner-recognition-reauth-form').addEventListener('submit', event => {
    event.preventDefault();
    void run('owner-recognition-reauth-status', async () => {
      const password = el('owner-recognition-password').value;
      await api(`${root}/reauth`, {method: 'POST', body: JSON.stringify({password})});
      el('owner-recognition-password').value = '';
      await load();
    }, event.submitter);
  });

  function stopVoiceStream() {
    // voiceRecorder.stop() fires its 'stop' listener asynchronously; that
    // listener closes over its own local `recorder`/`stream` (captured at
    // creation time below), not these outer variables, so nulling them
    // here first is safe and doesn't race the upload it still needs to do.
    if (voiceRecorder && voiceRecorder.state !== 'inactive') voiceRecorder.stop();
    if (voiceStream) { for (const track of voiceStream.getTracks()) track.stop(); }
    voiceStream = null; voiceRecorder = null;
    el('voice-sample-record').textContent = 'Start recording';
  }

  el('voice-sample-record').addEventListener('click', () => {
    void run('voice-sample-status', async () => {
      if (voiceRecorder && voiceRecorder.state === 'recording') { stopVoiceStream(); return; }
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      voiceStream = stream;
      voiceChunks = [];
      const recorder = new MediaRecorder(stream);
      voiceRecorder = recorder;
      recorder.addEventListener('dataavailable', event => { if (event.data.size) voiceChunks.push(event.data); });
      recorder.addEventListener('stop', () => {
        const blob = new Blob(voiceChunks, {type: recorder.mimeType || 'audio/webm'});
        voiceChunks = [];
        void run('voice-sample-status', async () => {
          if (!blob.size) { say('voice-sample-status', 'No audio captured; try again.'); return; }
          await apiUpload(`${root}/voice/samples`, blob);
          say('voice-sample-status', 'Voice sample saved.');
          await load();
        });
      });
      recorder.start();
      el('voice-sample-record').textContent = 'Stop recording';
      say('voice-sample-status', 'Recording… speak normally, then select Stop recording.');
    }, el('voice-sample-record'));
  });

  el('voice-sample-delete-all').addEventListener('click', event => {
    if (!window.confirm('Delete all recorded voice samples?')) return;
    void run('voice-sample-status', async () => {
      await api(`${root}/voice/samples`, {method: 'DELETE'});
      await load();
    }, event.target);
  });

  function stopFaceStream() {
    if (faceStream) { for (const track of faceStream.getTracks()) track.stop(); faceStream = null; }
    el('face-preview').hidden = true; el('face-preview').srcObject = null;
    el('face-sample-capture').hidden = true; el('face-sample-capture').disabled = true;
    el('face-sample-stop').hidden = true; el('face-sample-stop').disabled = true;
    el('face-sample-start').hidden = false;
  }

  el('face-sample-start').addEventListener('click', () => {
    void run('face-sample-status', async () => {
      faceStream = await navigator.mediaDevices.getUserMedia({video: {facingMode: 'user'}});
      el('face-preview').srcObject = faceStream;
      el('face-preview').hidden = false;
      el('face-sample-start').hidden = true;
      el('face-sample-capture').hidden = false; el('face-sample-capture').disabled = false;
      el('face-sample-stop').hidden = false; el('face-sample-stop').disabled = false;
      say('face-sample-status', 'Camera on. Frame your face, then select Capture photo.');
    }, el('face-sample-start'));
  });

  el('face-sample-stop').addEventListener('click', () => { stopFaceStream(); say('face-sample-status', ''); });

  el('face-sample-capture').addEventListener('click', event => {
    void run('face-sample-status', async () => {
      const video = el('face-preview');
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth; canvas.height = video.videoHeight;
      canvas.getContext('2d').drawImage(video, 0, 0);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9));
      if (!blob) { say('face-sample-status', 'Could not capture a photo; try again.'); return; }
      await apiUpload(`${root}/face/samples`, blob);
      say('face-sample-status', 'Face sample saved.');
      await load();
    }, event.target);
  });

  el('face-sample-delete-all').addEventListener('click', event => {
    if (!window.confirm('Delete all recorded face samples?')) return;
    void run('face-sample-status', async () => {
      await api(`${root}/face/samples`, {method: 'DELETE'});
      await load();
    }, event.target);
  });

  function stopCapture() { stopVoiceStream(); stopFaceStream(); }

  return {
    load,
    stopCapture,
    reset() {
      generation++; reauthenticated = false;
      stopCapture();
      el('owner-recognition-password').value = '';
      say('owner-recognition-reauth-status', '');
      say('voice-sample-status', ''); say('face-sample-status', '');
      el('voice-sample-list').replaceChildren(); el('face-sample-list').replaceChildren();
      el('voice-sample-record').disabled = true; el('voice-sample-delete-all').disabled = true;
      el('face-sample-start').disabled = true; el('face-sample-delete-all').disabled = true;
    },
  };
}
