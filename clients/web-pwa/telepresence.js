// Phase 16/ADR 0013: remote telepresence — camera view, live status,
// manual behaviour triggers, and speak-through-robot, all directly against
// reachy-hub with no companion-core involved. Every API call below carries
// the remote UI token as `Authorization: Bearer <token>` (see app.py's
// require_remote_auth) — entered once and kept in localStorage so it
// survives a reload, never sent anywhere except this page's own fetch
// calls to reachy-hub.
//
// Served by reachy-hub itself (see app.py's StaticFiles mount, same as
// index.html/"Call Reachy") and reached through Caddy at /hub/app/ — the
// API paths below are absolute from the page origin, matching app.js's
// same reasoning.
const HUB_BASE = "/hub";

const tokenInput = document.getElementById("token");
const robotIdInput = document.getElementById("robotId");
const connectButton = document.getElementById("connect");
const statusEl = document.getElementById("status");
const videoEl = document.getElementById("cameraFeed");
const behavioursEl = document.getElementById("behaviours");
const speakText = document.getElementById("speakText");
const speakButton = document.getElementById("speak");

let pc = null;
let statusPollHandle = null;

const savedToken = localStorage.getItem("remoteUiToken");
if (savedToken) tokenInput.value = savedToken;

function setStatus(text) {
  statusEl.textContent = text;
}

function authHeaders() {
  return { Authorization: `Bearer ${tokenInput.value}` };
}

async function apiFetch(path, options = {}) {
  const resp = await fetch(`${HUB_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if (!resp.ok) {
    throw new Error(`${path} -> ${resp.status}`);
  }
  return resp;
}

async function loadBehaviours(robotId) {
  const resp = await apiFetch(`/robots/${encodeURIComponent(robotId)}/behaviours`);
  const catalogue = await resp.json();
  behavioursEl.innerHTML = "";
  for (const name of Object.keys(catalogue).sort()) {
    const button = document.createElement("button");
    button.textContent = name;
    button.title = catalogue[name];
    button.addEventListener("click", () => triggerBehaviour(robotId, name));
    behavioursEl.appendChild(button);
  }
}

async function triggerBehaviour(robotId, name) {
  try {
    await apiFetch(`/robots/${encodeURIComponent(robotId)}/behaviour/${encodeURIComponent(name)}`, {
      method: "POST",
    });
  } catch (err) {
    console.error(err);
    setStatus(`behaviour failed: ${err.message}`);
  }
}

async function pollStatus(robotId) {
  try {
    const resp = await apiFetch(`/robots/${encodeURIComponent(robotId)}/state`);
    const state = await resp.json();
    setStatus(`${state.embodiment_state} — last: ${state.last_behaviour ?? "none"}`);
  } catch (err) {
    setStatus(`status unavailable: ${err.message}`);
  }
}

async function connectCamera(robotId) {
  pc = new RTCPeerConnection();
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.ontrack = (event) => {
    videoEl.srcObject = event.streams[0];
  };

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await waitForIceGatheringComplete(pc);

  const resp = await apiFetch("/webrtc/telepresence/offer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sdp: pc.localDescription.sdp,
      type: pc.localDescription.type,
      robot_id: robotId,
    }),
  });
  const answer = await resp.json();
  await pc.setRemoteDescription(answer);
}

function waitForIceGatheringComplete(peerConnection) {
  if (peerConnection.iceGatheringState === "complete") {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    function check() {
      if (peerConnection.iceGatheringState === "complete") {
        peerConnection.removeEventListener("icegatheringstatechange", check);
        resolve();
      }
    }
    peerConnection.addEventListener("icegatheringstatechange", check);
  });
}

async function connect() {
  const robotId = robotIdInput.value;
  localStorage.setItem("remoteUiToken", tokenInput.value);
  connectButton.disabled = true;
  setStatus("connecting...");

  try {
    await loadBehaviours(robotId);
    await connectCamera(robotId);
    speakButton.disabled = false;
    statusPollHandle = setInterval(() => pollStatus(robotId), 2000);
    pollStatus(robotId);
  } catch (err) {
    console.error(err);
    setStatus(`connect failed: ${err.message}`);
    connectButton.disabled = false;
  }
}

async function speak() {
  const robotId = robotIdInput.value;
  if (!speakText.value.trim()) return;
  speakButton.disabled = true;
  try {
    await apiFetch(`/robots/${encodeURIComponent(robotId)}/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: speakText.value }),
    });
    speakText.value = "";
  } catch (err) {
    console.error(err);
    setStatus(`speak failed: ${err.message}`);
  } finally {
    speakButton.disabled = false;
  }
}

connectButton.addEventListener("click", () => {
  connect();
});
speakButton.addEventListener("click", speak);

window.addEventListener("beforeunload", () => {
  if (statusPollHandle) clearInterval(statusPollHandle);
  if (pc) pc.close();
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch((err) => console.warn("service worker registration failed", err));
}
