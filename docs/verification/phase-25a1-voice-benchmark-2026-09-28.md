# Phase 25a.1 speaker-verification pipeline smoke test (2026-09-28)

**Scope:** the model-selection step
[phase-25.md's implementation sequence](../phase-25.md#implementation-sequence)
calls Phase 25a.1 — evaluate SpeechBrain ECAPA-TDNN and record model hashes
and versions. What ran here is a **pipeline smoke test on the dev box**,
not an owner-accuracy benchmark: no real Reachy microphone, homelab
hardware, or owner/non-owner recording took part. It confirms the scoring
pipeline itself behaves sanely (same speaker scores higher than different
speakers) before any real audio is collected, and records the exact
model/dependency versions to freeze once real benchmarking starts. Tooling
is in
[`benchmarks/phase-25a-speaker/`](../../benchmarks/phase-25a-speaker/),
deliberately kept outside the uv workspace per
[recommended dependency rollout](../phase-25.md#recommended-dependency-rollout).

## Setup

| Item | Value |
|---|---|
| Host | dev box (this session), not the homelab or Nano; 20 logical CPUs, CPU-only |
| Environment | isolated `venv` in `benchmarks/phase-25a-speaker/.venv`, not the workspace `.venv` |
| Dependencies | `torch==2.14.0+cpu`, `torchaudio==2.11.0+cpu` (PyTorch CPU index), `speechbrain==1.1.1`, `soundfile==0.14.0`, `numpy==2.5.3`, `huggingface_hub==2.0.0` |
| Model | `speechbrain/spkrec-ecapa-voxceleb`, Hugging Face snapshot `0f99f2d0ebe89ac095bcc5903c4dd8f72b367286`; license Apache-2.0 (from the repo's `license` card field, confirmed via `huggingface_hub.model_info`) |
| Clips | The model card's own two README example clips (VoxCeleb1 speaker ids 10003 and 10004), fetched from `cdn-media.huggingface.co/speech_samples/`; not the owner's voice, not a non-owner impostor trial |

## Results

**Pipeline sanity** (`verify_pair.py`, full-length clips, default 0.25
threshold):

| Pair | Cosine score | Accept |
|---|---|---|
| Same speaker (id10003 clip split into two halves) | 0.5323 | True |
| Different speakers (id10003 vs id10004) | 0.0167 | False |

Same-speaker and different-speaker trials separate in the expected
direction. This is one pair each, not a statistically meaningful FAR/FRR
estimate — see Limitations.

**Latency**, warm model, 5 repeated `verify_files` calls on trimmed 3 s
clips (closer to a real short spoken request than the ~10–18 s source
clips):

| | p50 | max |
|---|---|---|
| `verify_files`, 3 s clip pair | 0.49 s | 0.53 s |

The first (untrimmed, ~10–18 s) clip pair took about 1.2 s per call —
duration-dependent, as expected for embedding extraction. Model load
(`SpeakerRecognition.from_hparams`, warm HF cache) was a few seconds and is
a one-time cost, not per-utterance.

## Interpretation

- The SpeechBrain ECAPA-TDNN pipeline loads, runs and produces sane
  same/different-speaker separation with no code beyond the documented
  `verify_files` call — no blocking issue for choosing it as the Phase 25a
  baseline per [phase-25.md's library table](../phase-25.md#recommended-library-stack).
- 3 s-clip latency (~0.5 s p50 on a 20-core dev box) is compatible with the
  plan's intent to run STT and speaker verification concurrently
  (`asyncio.gather`) rather than sequentially, but this is dev-box CPU, not
  the homelab's — real concurrent-latency numbers still need measuring
  where the service will actually run.
- `torchaudio.load` on this torchaudio build requires the optional
  `torchcodec` package and fails without it; this benchmark used
  `soundfile` directly for the one place it needed to read/write audio
  outside SpeechBrain's own file handling. Worth resolving explicitly
  (pin an older torchaudio, or add `torchcodec`) before writing the
  production `reachy_hub/speaker/ecapa.py` adapter.

## Limitations and open items

- **No owner voice, no non-owner impostor trial, no replay/synthetic/
  overlap/noise condition.** Every required Phase 25a threat scenario
  (docs/phase-25.md's "Required threat scenarios") is still untested. This
  smoke test only shows the scoring mechanism itself isn't broken.
- **Not run on the homelab**, where 25a.3 will actually deploy speaker
  verification (to avoid Nano ARM/RAM cost per the dependency-rollout
  section). Latency and resource cost on that host are unmeasured.
- **AASIST anti-spoof path not evaluated.** It isn't a pip-installable
  package like SpeechBrain; benchmarking it needs cloning its research repo
  and pretrained weights separately, deferred to its own pass.
- **No calibration.** The 0.25 cosine threshold used by `verify_files` is
  SpeechBrain's own default, not a calibrated decision score on
  Reachy-deployment-condition data (docs/phase-25.md's confidence/threat
  model section requires per-modality calibration before any percentage-
  based acceptance is used for a trust level).

**Next step for 25a.1:** collect real, consenting owner and non-owner audio
through the actual Reachy microphone/upload path (or at minimum a
representative recording setup) before drawing any accuracy conclusion;
this smoke test only clears the "does the pipeline work at all" bar.
