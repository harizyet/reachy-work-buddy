FROM python:3.13-slim

# espeak-ng: the local TTS provider (Phase 8, tts.py) — no cloud TTS key is
# available, so this is the real, working default. A cloud provider
# (ElevenLabs etc.) implementing the same TextToSpeech protocol removes
# this system dependency when one is added.
RUN apt-get update && apt-get install -y --no-install-recommends espeak-ng \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY shared/ shared/
COPY services/reachy-hub/ services/reachy-hub/
# The "Call Reachy" PWA (Phase 15) — reachy-hub serves it directly (ADR
# 0001: reachy-hub owns web UI), see app.py's StaticFiles mount.
COPY clients/web-pwa/ clients/web-pwa/

RUN uv sync --frozen --no-dev --package reachy-hub

EXPOSE 8000
# See reachy-embodiment/Dockerfile for why this calls the venv directly
# instead of `uv run`.
CMD ["/app/.venv/bin/uvicorn", "reachy_hub.main:app", "--app-dir", "services/reachy-hub/src", "--host", "0.0.0.0", "--port", "8000"]
