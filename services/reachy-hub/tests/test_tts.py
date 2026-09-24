import io
import os
import shutil
import wave

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


@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_synthesize_writes_the_real_frame_count_not_espeaks_placeholder() -> None:
    # Phase 24c: the robot times playback from this header.
    import io
    import wave

    wav_bytes = EspeakTTS().synthesize("a short sentence")
    with wave.open(io.BytesIO(wav_bytes)) as wav:
        frames = wav.getnframes()
        seconds = frames / wav.getframerate()
        assert len(wav.readframes(frames)) == frames * wav.getsampwidth() * wav.getnchannels()
    assert 0.3 < seconds < 5


def test_default_tts_is_espeak_without_a_piper_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    from reachy_hub.tts import default_tts

    monkeypatch.delenv("PIPER_VOICE_MODEL", raising=False)
    assert isinstance(default_tts(), EspeakTTS)


piper_model = os.environ.get("PIPER_VOICE_MODEL")


@pytest.mark.slow
@pytest.mark.skipif(not piper_model, reason="PIPER_VOICE_MODEL not set")
def test_piper_voice_is_selected_and_intelligible_to_whisper() -> None:
    from reachy_hub.stt import FasterWhisperSTT
    from reachy_hub.tts import PiperTTS, default_tts

    tts = default_tts()
    assert isinstance(tts, PiperTTS)
    wav_bytes = tts.synthesize("The quick brown fox jumps over the lazy dog.")
    with wave.open(io.BytesIO(wav_bytes)) as wav:
        frames = wav.getnframes()
        assert len(wav.readframes(frames)) == frames * wav.getsampwidth() * wav.getnchannels()
        assert 1 < frames / wav.getframerate() < 6
    transcript = FasterWhisperSTT(model_size="tiny.en").transcribe(wav_bytes).lower()
    assert "quick brown fox" in transcript
    # An empty reply must still produce a WAV, not raise mid-turn.
    assert tts.synthesize("")[:4] == b"RIFF"
