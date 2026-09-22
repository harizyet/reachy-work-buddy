"""Phase 16/ADR 0013: remote telepresence — auth, direct speak-through-robot
(no companion-core involved), and a real (not mocked) WebRTC video
negotiation for the camera feed.

The camera test uses a real aiortc peer as the "browser" (no browser exists
in this environment — same standing approach as test_webrtc_call_live.py),
but doesn't need `@pytest.mark.slow`: unlike the "Call Reachy" round trip,
nothing here loads a real STT/TTS model.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import wave

import httpx
from aiortc import RTCPeerConnection, RTCSessionDescription
from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app as create_embodiment_app
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore

TEST_TOKEN = "test-remote-token"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _fake_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x01" * 100)
    return buf.getvalue()


class _FakeTTS:
    def __init__(self) -> None:
        self.synthesized: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.synthesized.append(text)
        return _fake_wav()


def _make_hub_app(**kwargs):
    kwargs.setdefault("remote_ui_token", TEST_TOKEN)
    embodiment_app = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
    hub_app = create_app(
        registry=InMemoryRobotRegistry(),
        session_store=InMemorySessionStore(),
        audit_log=InMemoryAuditLog(),
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        run_heartbeat_task=False,
        **kwargs,
    )
    return hub_app, embodiment_app


def test_robot_endpoints_401_without_a_token() -> None:
    hub_app, _ = _make_hub_app()
    client = TestClient(hub_app)
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"}, headers=AUTH_HEADERS)

    assert client.get("/robots/desk-1/state").status_code == 401
    assert client.get("/robots/desk-1/state", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/robots/desk-1/state", headers=AUTH_HEADERS).status_code == 200


def test_robot_endpoints_503_when_remote_ui_token_is_not_configured() -> None:
    hub_app, _ = _make_hub_app(remote_ui_token=None)
    client = TestClient(hub_app)
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})

    resp = client.get("/robots/desk-1/state", headers=AUTH_HEADERS)
    assert resp.status_code == 503


def test_speak_synthesizes_and_plays_through_the_robot_without_companion_core() -> None:
    """Phase 16 exit criterion, literal wording. No companion_core_client
    was ever given a reachable transport here (it defaults to an
    unresolvable hostname) — /messages would fail against it, /speak never
    touches it at all."""
    fake_tts = _FakeTTS()
    hub_app, embodiment_app = _make_hub_app(tts=fake_tts)
    client = TestClient(hub_app)
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"}, headers=AUTH_HEADERS)

    resp = client.post("/robots/desk-1/speak", json={"text": "hello from overseas"}, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["last_behaviour"] == "speaking"
    assert fake_tts.synthesized == ["hello from overseas"]

    # Reverted to idle — no telepresence session was active.
    assert embodiment_app.state.service_state.embodiment_state == "idle"


def test_real_webrtc_telepresence_offer_streams_the_real_camera_track() -> None:
    async def run() -> None:
        hub_app, embodiment_app = _make_hub_app()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=hub_app), base_url="http://hub") as http:
            await http.post(
                "/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"}, headers=AUTH_HEADERS
            )

            client_pc = RTCPeerConnection()
            received_frames = []

            @client_pc.on("track")
            def on_track(track) -> None:
                async def read_loop() -> None:
                    with contextlib.suppress(Exception):
                        while True:
                            frame = await track.recv()
                            received_frames.append(frame)

                asyncio.ensure_future(read_loop())

            client_pc.addTransceiver("video", direction="recvonly")
            offer = await client_pc.createOffer()
            await client_pc.setLocalDescription(offer)
            await _wait_ice_complete(client_pc)

            resp = await http.post(
                "/webrtc/telepresence/offer",
                json={"sdp": client_pc.localDescription.sdp, "type": client_pc.localDescription.type, "robot_id": "desk-1"},
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 200
            answer = resp.json()
            await client_pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))

            for _ in range(100):  # up to ~10s
                if received_frames:
                    break
                await asyncio.sleep(0.1)
            assert received_frames, "no real video frame was ever received over the peer connection"

            # ADR 0013: connecting marks the robot REMOTE (previously-unused
            # EmbodimentState.REMOTE, since Phase 3/ADR 0004).
            assert embodiment_app.state.service_state.embodiment_state == "remote"

            await client_pc.close()
            for pc in list(hub_app.state.webrtc_connections):
                await pc.close()

            # Closing the peer connection reverts the robot out of REMOTE.
            for _ in range(50):
                if embodiment_app.state.service_state.embodiment_state != "remote":
                    break
                await asyncio.sleep(0.1)
            assert embodiment_app.state.service_state.embodiment_state == "idle"

    asyncio.run(run())


async def _wait_ice_complete(pc: RTCPeerConnection) -> None:
    if pc.iceGatheringState == "complete":
        return
    done = asyncio.Event()

    @pc.on("icegatheringstatechange")
    def _on_change() -> None:
        if pc.iceGatheringState == "complete":
            done.set()

    await asyncio.wait_for(done.wait(), timeout=10)
