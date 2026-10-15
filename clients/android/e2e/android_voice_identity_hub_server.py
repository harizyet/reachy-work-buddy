"""Throwaway hub for the Android voice-identity integration test: a REAL in-process hub (real routes, real encrypted profile store with a real keyring, real owner
login, real benchmark store) with a deterministic stand-in for the two heavy models. The "speaker embedding" is the clip's dominant pitch (zero crossings), so a 220 Hz
tone is the owner and a 440 Hz tone is someone else; the "recogniser" returns a fixed sentence. Nothing here is a deployment.

    python clients/android/e2e/android_voice_identity_hub_server.py PORT [calibrated]

Owner login `owner` / `correct-password`. The JVM test `VoiceIdentityHubIntegrationTest` runs against it when REACHY_E2E_HUB is set.
"""

import asyncio
import io
import itertools
import math
import sys
import wave

import uvicorn
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.enrollment_store import InMemoryEnrollmentStore
from reachy_hub.keyring import Keyring
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.user_store import InMemoryUserStore
from reachy_hub.voice_identity import Embedding, VoiceIdentityConfig
from reachy_hub.voice_profiles import InMemoryVoiceProfileStore


class PitchEmbedder:
    model_version = "pitch-fixture@1"

    async def embed(self, data: bytes) -> Embedding:
        with wave.open(io.BytesIO(data), "rb") as w:
            frames = w.readframes(w.getnframes())
            rate = w.getframerate()
        samples = [int.from_bytes(frames[i:i + 2], "little", signed=True) for i in range(0, len(frames), 2)]
        seconds = len(samples) / rate
        crossings = sum(1 for a, b in itertools.pairwise(samples) if (a < 0) != (b < 0))
        pitch = crossings / 2 / seconds if seconds else 0.0
        angle = math.radians(max(min((pitch - 220.0) / 220.0 * 90.0, 180.0), -180.0))
        rms = math.sqrt(sum((s / 32768.0) ** 2 for s in samples) / max(len(samples), 1))
        loud = rms > 0.01
        return Embedding([math.cos(angle), math.sin(angle), 0.0, 0.0], self.model_version, seconds, seconds if loud else 0.0,
                         20 * math.log10(rms + 1e-6), 0.0)

    async def healthy(self) -> bool:
        return True


class FixedSTT:
    def transcribe(self, wav_bytes, vocabulary=()):
        return "hello from the phone"


def build(calibrated: bool):
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    config = VoiceIdentityConfig(enabled=True, accept_threshold=0.8 if calibrated else None, uncertain_threshold=0.5 if calibrated else None,
                                 calibration_version="fixture" if calibrated else "uncalibrated")
    return create_app(
        user_store=users, registry=InMemoryRobotRegistry(), session_store=InMemorySessionStore(), audit_log=InMemoryAuditLog(),
        notification_queue=InMemoryNotificationQueue(), enrollment_store=InMemoryEnrollmentStore(), run_heartbeat_task=False,
        run_telegram_poll_task=False, session_secret_key="fixture-session-secret", remote_ui_token="fixture-token", stt=FixedSTT(),
        voice_identity_config=config, voice_embedder=PitchEmbedder(), voice_profile_store=InMemoryVoiceProfileStore(),
        voice_keyring=Keyring("k1", {"k1": bytes(range(32))}),
    )


if __name__ == "__main__":
    uvicorn.run(build("calibrated" in sys.argv[2:]), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
