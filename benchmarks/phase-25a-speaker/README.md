# Phase 25a.1 speaker-verification benchmark environment

Deliberately kept out of the uv workspace, per
[docs/phase-25.md's recommended dependency rollout](../../docs/phase-25.md#recommended-dependency-rollout):
do not add biometric libraries to the production `reachy-hub` image during
exploration. This directory has its own `.venv` and is not referenced by
the root `pyproject.toml`, `uv.lock`, or any service's dependencies.

See
[docs/verification/phase-25a1-voice-benchmark-2026-09-28.md](../../docs/verification/phase-25a1-voice-benchmark-2026-09-28.md)
for what was actually measured and its limitations — most importantly,
**no real Reachy owner/non-owner recording was used here**; this only
validates that the scoring pipeline itself behaves sanely.

## Reproduce

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
pip install -r requirements.txt
python verify_pair.py
```

The first run downloads the pretrained
`speechbrain/spkrec-ecapa-voxceleb` model (Apache-2.0) from Hugging Face
into `pretrained_models/` (gitignored) and the two public VoxCeleb example
clips referenced by that model's card into `samples/` (gitignored).
