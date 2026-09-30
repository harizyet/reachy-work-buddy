"""Run inside either speech image: python /tests/test_speech_uploads.py.

Uses that image's real decoder dependencies with fake inference to check
upload ownership and admission. Does not load/download models.
"""
import importlib.util
import io
import os
import unittest
import wave
from types import SimpleNamespace

from fastapi import HTTPException, UploadFile

spec = importlib.util.spec_from_file_location("speech_server_under_test", os.environ.get("TEST_SPEECH_SERVER", "/app/server.py"))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class BoundedUpload(io.BytesIO):
    def read(self, size=-1):
        if size < 0:
            raise AssertionError("encoded audio read wholesale")
        return super().read(size)


class SpeechUploadTests(unittest.TestCase):
    def setUp(self):
        self.is_stt = hasattr(server, "transcribe")
        self.endpoint = server.transcribe if self.is_stt else server.diarize
        server.S["status"] = "ready"
        self.seen = False

    def upload(self, malformed=False):
        data = io.BytesIO()
        with wave.open(data, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(bytes(32000))
        return UploadFile(BoundedUpload(b"invalid" if malformed else data.getvalue()), filename="audio.wav")

    def set_model(self, fail=False):
        def transcribe(stream, **kwargs):
            self.seen = True
            with wave.open(stream) as wav:
                assert wav.getnframes() == 16000
            if fail:
                raise ValueError("model failure")
            return iter([SimpleNamespace(start=0, end=1, text=" hello ")]), SimpleNamespace(duration=1, language="en")

        def diarize(paths, **kwargs):
            self.seen = True
            with wave.open(paths[0]) as wav:
                assert wav.getnframes() == 16000
            if fail:
                raise ValueError("model failure")
            return [["0.0 1.0 speaker_0"]]

        server.S["model"] = SimpleNamespace(transcribe=transcribe)
        server.S["diarizer"] = SimpleNamespace(diarize=diarize)

    def test_busy_does_not_decode_or_queue(self):
        server.lock.acquire()
        try:
            with self.assertRaises(HTTPException) as caught:
                self.endpoint(self.upload(malformed=True))
            self.assertEqual(caught.exception.status_code, 503)
            self.assertTrue(server.lock.locked())
        finally:
            server.lock.release()

    def test_file_backed_upload_and_lock_release(self):
        self.set_model()
        result = self.endpoint(self.upload())
        self.assertTrue(self.seen)
        self.assertEqual(result["duration_s"], 1)
        self.assertEqual(len(result["segments"]), 1)
        self.assertFalse(server.lock.locked())

    def test_failed_decode_releases_lock(self):
        self.set_model()
        with self.assertRaises(HTTPException) as caught:
            self.endpoint(self.upload(malformed=True))
        self.assertEqual(caught.exception.status_code, 400)
        self.assertFalse(server.lock.locked())

    def test_failed_inference_releases_lock(self):
        self.set_model(fail=True)
        with self.assertRaises((HTTPException, ValueError)):
            self.endpoint(self.upload())
        self.assertTrue(self.seen)
        self.assertFalse(server.lock.locked())


if __name__ == "__main__":
    unittest.main()
