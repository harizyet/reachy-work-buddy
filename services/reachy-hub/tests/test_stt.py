import shutil

import pytest
from reachy_hub.stt import FasterWhisperSTT
from reachy_hub.tts import EspeakTTS

espeak_binary = shutil.which("espeak-ng")


@pytest.mark.slow
@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_transcribe_a_real_synthesized_utterance() -> None:
    """Round-trip: synthesize real speech audio with the (real, local) TTS
    provider, feed it into the (real) STT provider, and confirm the words
    come back out. Both providers are genuinely doing their jobs here —
    nothing is mocked."""
    tts = EspeakTTS()
    # Avoid phonetically ambiguous words: an early version of this test used
    # "...lazy dog", which espeak-ng's robotic voice pronounced closely
    # enough to "nog" that tiny.en misheard it — a genuine STT/TTS quality
    # limitation of these deliberately lightweight, local, no-API-key
    # components, not a bug in our code. Picked words here are phonetically
    # distinct enough to be robust to that.
    wav_bytes = tts.synthesize("hello world, this is a test of speech recognition")

    stt = FasterWhisperSTT(model_size="tiny.en")
    transcript = stt.transcribe(wav_bytes)

    lowered = transcript.lower()
    assert "hello" in lowered
    assert "world" in lowered
    assert "speech" in lowered


@pytest.mark.slow
def test_transcribe_silence_returns_empty_string() -> None:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000)  # 1s of silence

    stt = FasterWhisperSTT(model_size="tiny.en")
    transcript = stt.transcribe(buf.getvalue())
    assert transcript == ""
