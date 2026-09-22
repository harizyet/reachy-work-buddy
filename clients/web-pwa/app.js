// Phase 15 "Call Reachy": real WebRTC audio to reachy-hub. Push-to-talk,
// not continuous VAD (see services/reachy-hub/src/reachy_hub/webrtc.py's
// module docstring for why) — audio only actually leaves the mic while
// the talk button is held; a "control" data channel carries the
// start_talk/end_talk signals reachy-hub uses to know when to run STT.
//
// The page is served by reachy-hub itself and reached through Caddy at
// /hub/app/ (see docker-compose.yml/Caddyfile) — so the signaling
// endpoint below is an *absolute* path from the page origin, not relative
// to /hub/app/, matching how Caddy's handle_path strips the /hub prefix
// only for requests that start with it.
const OFFER_URL = "/hub/webrtc/offer";

const connectButton = document.getElementById("connect");
const talkButton = document.getElementById("talk");
const statusEl = document.getElementById("status");
const remoteAudio = document.getElementById("remoteAudio");
const userIdInput = document.getElementById("userId");
const robotIdInput = document.getElementById("robotId");

let pc = null;
let controlChannel = null;
let localTrack = null;

function setStatus(text) {
  statusEl.textContent = text;
}

async function connect() {
  connectButton.disabled = true;
  setStatus("requesting microphone...");

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  localTrack = stream.getAudioTracks()[0];
  localTrack.enabled = false; // push-to-talk: silent until the talk button is held

  pc = new RTCPeerConnection();
  pc.addTrack(localTrack, stream);

  pc.ontrack = (event) => {
    remoteAudio.srcObject = event.streams[0];
  };

  controlChannel = pc.createDataChannel("control");
  controlChannel.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "status") {
        setStatus(payload.state);
      }
    } catch (err) {
      console.warn("unrecognized control message", event.data, err);
    }
  };
  controlChannel.onopen = () => {
    talkButton.disabled = false;
    setStatus("connected — hold the button to talk");
  };

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  // Non-trickle ICE: wait for gathering to finish so the single HTTP POST
  // below carries a complete SDP, no separate ICE-candidate signaling
  // channel needed. Fine on a local/LAN homelab call; see webrtc.py's
  // module docstring for the known cross-machine/Docker-NAT limitation.
  await waitForIceGatheringComplete(pc);

  const response = await fetch(OFFER_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sdp: pc.localDescription.sdp,
      type: pc.localDescription.type,
      user_id: userIdInput.value,
      robot_id: robotIdInput.value,
    }),
  });
  if (!response.ok) {
    setStatus(`call failed: ${response.status}`);
    connectButton.disabled = false;
    return;
  }
  const answer = await response.json();
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

function startTalk() {
  if (!localTrack || !controlChannel || controlChannel.readyState !== "open") return;
  localTrack.enabled = true;
  talkButton.classList.add("armed");
  controlChannel.send(JSON.stringify({ type: "start_talk" }));
}

function endTalk() {
  if (!localTrack || !controlChannel || controlChannel.readyState !== "open") return;
  localTrack.enabled = false;
  talkButton.classList.remove("armed");
  controlChannel.send(JSON.stringify({ type: "end_talk" }));
}

connectButton.addEventListener("click", () => {
  connect().catch((err) => {
    console.error(err);
    setStatus(`error: ${err.message}`);
    connectButton.disabled = false;
  });
});

talkButton.addEventListener("pointerdown", startTalk);
talkButton.addEventListener("pointerup", endTalk);
talkButton.addEventListener("pointerleave", endTalk);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch((err) => console.warn("service worker registration failed", err));
}
