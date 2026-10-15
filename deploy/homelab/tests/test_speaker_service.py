"""Speaker service contract tests (Phase 32A.V): run inside the speaker image, or anywhere numpy and fastapi exist:
TEST_SPEAKER_SERVER=deploy/homelab/speaker/app/server.py python deploy/homelab/tests/test_speaker_service.py
A fake embedder stands in for the model, so nothing is downloaded; this checks the audio contract, quality facts and statelessness."""
import importlib.util
import io
import os
import unittest
import wave

import numpy as np
from fastapi import HTTPException, UploadFile

spec = importlib.util.spec_from_file_location("speaker_server_under_test", os.environ.get("TEST_SPEAKER_SERVER", "/app/server.py"))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def wav_bytes(samples: np.ndarray, rate=16000, channels=1) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


def tone(seconds=2.0, amp=0.3):
    t = np.arange(int(16000 * seconds)) / 16000
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


class FakeEmbedder:
    def __init__(self):
        self.seen = []

    def embed(self, samples):
        self.seen.append(len(samples))
        return [0.1, 0.2, 0.3]


def upload(data: bytes) -> UploadFile:
    return UploadFile(io.BytesIO(data), filename="a.wav")


class SpeakerServiceTests(unittest.TestCase):
    def setUp(self):
        server.S["status"], server.S["embedder"] = "ready", FakeEmbedder()

    def test_embeds_mono_16k_wav_and_reports_quality(self):
        body = server.embed(upload(wav_bytes(tone())))
        self.assertEqual(body["embedding"], [0.1, 0.2, 0.3])
        self.assertEqual(body["model_version"], server.MODEL_VERSION)
        self.assertAlmostEqual(body["duration_s"], 2.0, places=2)
        self.assertGreater(body["speech_s"], 1.5)
        self.assertLess(body["rms_dbfs"], -5)
        self.assertEqual(body["clipping_fraction"], 0.0)

    def test_silence_has_no_speech_and_clipping_is_reported(self):
        silent = server.quality(np.zeros(32000, dtype=np.float32))
        self.assertEqual(silent["speech_s"], 0.0)
        self.assertLess(silent["rms_dbfs"], -90)
        self.assertGreater(server.quality(np.sign(tone()))["clipping_fraction"], 0.9)

    def test_other_formats_are_refused_not_resampled(self):
        for data in (wav_bytes(tone(), rate=8000), wav_bytes(np.stack([tone(), tone()], axis=1).reshape(-1), channels=2), b"not audio"):
            with self.assertRaises(HTTPException) as caught:
                server.embed(upload(data))
            self.assertEqual(caught.exception.status_code, 422)

    def test_too_short_empty_and_oversize(self):
        for data, code in ((wav_bytes(tone(0.2)), 422), (b"", 400), (b"x" * (server.MAX_AUDIO_BYTES + 1), 413)):
            with self.assertRaises(HTTPException) as caught:
                server.embed(upload(data))
            self.assertEqual(caught.exception.status_code, code)

    def test_not_ready_and_busy(self):
        server.S["status"] = "loading"
        with self.assertRaises(HTTPException) as caught:
            server.embed(upload(wav_bytes(tone())))
        self.assertEqual(caught.exception.status_code, 503)
        server.S["status"] = "ready"
        self.assertTrue(server.lock.acquire(blocking=False))
        try:
            with self.assertRaises(HTTPException) as caught:
                server.embed(upload(wav_bytes(tone())))
            self.assertEqual(caught.exception.status_code, 503)
        finally:
            server.lock.release()

    def test_service_token_is_enforced_when_configured(self):
        server.SPEECH_SERVICE_TOKEN = "secret"
        try:
            with self.assertRaises(HTTPException):
                server.require_service_token(None)
            with self.assertRaises(HTTPException):
                server.require_service_token("wrong")
            server.require_service_token("secret")
        finally:
            server.SPEECH_SERVICE_TOKEN = None


if __name__ == "__main__":
    unittest.main()
