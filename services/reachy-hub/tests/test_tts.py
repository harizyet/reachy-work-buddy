import shutil

import pytest
from reachy_hub.tts import EspeakTTS

espeak_binary = shutil.which("espeak-ng")


@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_synthesize_produces_a_real_wav_file() -> None:
    tts = EspeakTTS()
    wav_bytes = tts.synthesize("hello this is a real local text to speech test")

    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"
    assert len(wav_bytes) > 1000  # a few words of speech is not a tiny file


@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_synthesize_empty_text_still_returns_a_valid_wav() -> None:
    tts = EspeakTTS()
    wav_bytes = tts.synthesize("")
    assert wav_bytes[:4] == b"RIFF"
