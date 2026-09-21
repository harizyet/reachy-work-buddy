"""VAD tests against real synthesized speech, not tones or noise — a sine
wave doesn't have the formant structure Silero VAD is trained to detect, so
using it would prove nothing. espeak-ng (already used as the Phase 8 local
TTS provider in reachy-hub) synthesizes real speech audio here purely as a
test fixture; resampled from its native 22050Hz to the 16kHz Silero
requires.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import wave

import numpy as np
import pytest
from reachy_embodiment.audio.vad import (
    CHUNK_SAMPLES,
    SAMPLE_RATE,
    VoiceActivityDetector,
)

espeak_binary = shutil.which("espeak-ng")


def _synthesize_16k_mono(text: str) -> np.ndarray:
    result = subprocess.run(
        [espeak_binary, "-v", "en-us", "--stdout", text],
        capture_output=True,
        check=True,
    )
    with wave.open(io.BytesIO(result.stdout)) as wav_file:
        assert wav_file.getnchannels() == 1
        raw = wav_file.readframes(wav_file.getnframes())
        native_rate = wav_file.getframerate()

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if native_rate == SAMPLE_RATE:
        return samples

    duration = len(samples) / native_rate
    target_len = int(duration * SAMPLE_RATE)
    src_x = np.linspace(0, duration, num=len(samples), endpoint=False)
    dst_x = np.linspace(0, duration, num=target_len, endpoint=False)
    return np.interp(dst_x, src_x, samples).astype(np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


def _pad_to_chunk_multiple(samples: np.ndarray) -> np.ndarray:
    remainder = len(samples) % CHUNK_SAMPLES
    if remainder == 0:
        return samples
    return np.concatenate([samples, np.zeros(CHUNK_SAMPLES - remainder, dtype=np.float32)])


@pytest.mark.slow
@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_detects_speech_surrounded_by_silence() -> None:
    speech = _synthesize_16k_mono("this is a real spoken sentence for testing voice activity detection")
    samples = _pad_to_chunk_multiple(np.concatenate([_silence(1.0), speech, _silence(1.0)]))

    vad = VoiceActivityDetector()
    segments = vad.extract_speech_segments(samples)

    assert len(segments) >= 1
    start, end = segments[0]
    # The detected segment should land roughly where the ~1s of leading
    # silence ends, with some tolerance for Silero's own onset/offset lag.
    assert 0.5 * SAMPLE_RATE < start < 1.5 * SAMPLE_RATE
    assert end > start


@pytest.mark.slow
@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_pure_silence_detects_no_speech() -> None:
    samples = _pad_to_chunk_multiple(_silence(2.0))
    vad = VoiceActivityDetector()
    assert vad.extract_speech_segments(samples) == []


def test_process_chunk_rejects_wrong_length() -> None:
    vad = VoiceActivityDetector()
    with pytest.raises(ValueError):
        vad.process_chunk(np.zeros(CHUNK_SAMPLES - 1, dtype=np.float32))


def test_rejects_non_16khz_sample_rate() -> None:
    with pytest.raises(ValueError):
        VoiceActivityDetector(sample_rate=8000)
