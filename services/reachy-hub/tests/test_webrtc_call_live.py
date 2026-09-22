"""A real (not mocked) end-to-end WebRTC call: a real aiortc client peer
negotiates with reachy-hub's real POST /webrtc/offer, sends real audio
(synthesized speech) over a real media connection, and gets real
synthesized speech back — the same STT/TTS/embodiment chain
test_voice.py proves for POST /voice/turn, but over WebRTC with
push-to-talk instead of a single WAV upload. Marked slow: this is real
STT/TTS/DTLS/ICE negotiation, not something to run on every fast pass.

There is no browser in this environment, so the "browser" side here is a
second real aiortc RTCPeerConnection — a genuine WebRTC peer, just not a
browser — matching this codebase's standing preference for real
infrastructure over mocks wherever practical (see AGENTS.md's
"Verifying claims").
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil

import httpx
import numpy as np
import pytest
from aiortc import RTCPeerConnection, RTCSessionDescription
from companion_core.app import create_app as _create_core_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from reachy_embodiment.app import create_app as create_embodiment_app
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.robot_registry import InMemoryRobotRegistry, Robot
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.stt import FasterWhisperSTT
from reachy_hub.tts import EspeakTTS
from reachy_hub.webrtc import WavPlaybackTrack

espeak_binary = shutil.which("espeak-ng")


def _create_core_test_app():
    return _create_core_app(
        calendar_store=InMemoryCalendarStore(),
        task_store=InMemoryTaskStore(),
        memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(),
        confirmation_store=InMemoryConfirmationStore(),
        run_email_dispatch_task=False,
    )


@pytest.mark.slow
@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_real_webrtc_call_round_trips_real_audio_and_drives_real_embodiment() -> None:
    async def run() -> None:
        embodiment_app = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
        core_app = _create_core_test_app()
        hub_app = create_app(
            registry=InMemoryRobotRegistry(),
            session_store=InMemorySessionStore(),
            audit_log=InMemoryAuditLog(),
            client_factory=lambda base_url: EmbodimentClient(
                base_url, transport=httpx.ASGITransport(app=embodiment_app)
            ),
            companion_core_client=CompanionCoreClient(
                "http://companion-core", transport=httpx.ASGITransport(app=core_app)
            ),
            run_heartbeat_task=False,
            stt_factory=lambda: FasterWhisperSTT(model_size="tiny.en"),
            tts_factory=EspeakTTS,
            remote_ui_token="test-remote-token",
        )
        robot = Robot(robot_id="desk-1", base_url="http://desk-1.local")
        await hub_app.state.registry.register(robot)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=hub_app), base_url="http://hub") as http:
            # The "browser": a second, genuinely separate aiortc peer.
            client_pc = RTCPeerConnection()
            question_wav = EspeakTTS().synthesize("hello there")
            client_pc.addTrack(WavPlaybackTrack(question_wav))

            received_frames: list[np.ndarray] = []

            @client_pc.on("track")
            def on_track(track) -> None:
                async def read_loop() -> None:
                    with contextlib.suppress(Exception):
                        while True:
                            frame = await track.recv()
                            received_frames.append(frame.to_ndarray())

                asyncio.ensure_future(read_loop())

            control = client_pc.createDataChannel("control")
            statuses: list[str] = []
            control_open = asyncio.Event()

            @control.on("open")
            def on_open() -> None:
                control_open.set()

            @control.on("message")
            def on_message(message: str) -> None:
                payload = json.loads(message)
                if payload.get("type") == "status":
                    statuses.append(payload["state"])

            offer = await client_pc.createOffer()
            await client_pc.setLocalDescription(offer)
            await _wait_ice_complete(client_pc)

            resp = await http.post(
                "/webrtc/offer",
                json={
                    "sdp": client_pc.localDescription.sdp,
                    "type": client_pc.localDescription.type,
                    "user_id": "hariz",
                    "robot_id": "desk-1",
                },
            )
            assert resp.status_code == 200
            answer = resp.json()
            await client_pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))

            await asyncio.wait_for(control_open.wait(), timeout=10)

            # Push-to-talk: hold for slightly longer than the question WAV.
            control.send(json.dumps({"type": "start_talk"}))
            question_seconds = len(question_wav) / (16000 * 2)  # rough upper bound, sampwidth=2 mono-ish
            await asyncio.sleep(question_seconds + 1.0)
            control.send(json.dumps({"type": "end_talk"}))

            # Wait for the real STT -> agent -> TTS round trip and for real
            # audio frames to actually arrive back over the connection.
            for _ in range(200):  # up to ~20s
                if any(arr.any() for arr in received_frames):
                    break
                await asyncio.sleep(0.1)

            assert "listening" in statuses
            assert "thinking" in statuses
            assert "speaking" in statuses
            assert any(arr.any() for arr in received_frames), "no real (non-silent) reply audio was ever received"

            robot_state = await http.get(
                "/robots/desk-1/state", headers={"Authorization": "Bearer test-remote-token"}
            )
            assert robot_state.status_code == 200
            # By the time real audio has arrived the call already passed
            # through listening/thinking/speaking on the real embodiment.
            assert robot_state.json()["last_behaviour"] in ("speaking", "waiting")

            await client_pc.close()
            for pc in list(hub_app.state.webrtc_connections):
                await pc.close()

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
