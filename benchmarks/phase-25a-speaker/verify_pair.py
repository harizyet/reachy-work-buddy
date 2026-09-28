"""Phase 25a.1 pipeline smoke test (docs/phase-25.md#implementation-sequence).

Not an owner-accuracy benchmark: these two clips are the speechbrain
spkrec-ecapa-voxceleb model card's own two-speaker README examples
(VoxCeleb1 ids 10003/10004), used only to confirm the scoring pipeline
behaves sanely (same speaker scores higher than different speakers) before
any real Reachy owner/non-owner recording is collected. Real accuracy
numbers require actual held-out owner/non-owner audio captured through the
real Reachy microphone path, per docs/phase-25.md's threat-model
requirements, and are not produced by this script.
"""

from __future__ import annotations

import soundfile as sf
from speechbrain.inference.speaker import SpeakerRecognition

MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"


def load_model() -> SpeakerRecognition:
    return SpeakerRecognition.from_hparams(
        source=MODEL_SOURCE,
        savedir="pretrained_models/ecapa-voxceleb",
    )


def split_in_half(path: str, out_a: str, out_b: str) -> None:
    waveform, sample_rate = sf.read(path)
    midpoint = len(waveform) // 2
    sf.write(out_a, waveform[:midpoint], sample_rate)
    sf.write(out_b, waveform[midpoint:], sample_rate)


def main() -> None:
    model = load_model()

    split_in_half("samples/speaker_a.wav", "samples/speaker_a_1.wav", "samples/speaker_a_2.wav")

    same_speaker_score, same_speaker_decision = model.verify_files(
        "samples/speaker_a_1.wav", "samples/speaker_a_2.wav"
    )
    different_speaker_score, different_speaker_decision = model.verify_files(
        "samples/speaker_a.wav", "samples/speaker_b.wav"
    )

    print(f"same-speaker (a-half1 vs a-half2):      score={float(same_speaker_score):.4f} accept={bool(same_speaker_decision)}")
    print(f"different-speaker (a vs b):              score={float(different_speaker_score):.4f} accept={bool(different_speaker_decision)}")


if __name__ == "__main__":
    main()
