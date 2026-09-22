# syntax=docker/dockerfile:1
# The syntax pragma above opts into BuildKit's Dockerfile frontend, which
# `--mount=type=cache` below requires — building this file needs BuildKit
# (the `docker buildx` CLI plugin; see AGENTS.md's Dev setup section for
# how to install it without root if it's missing).
FROM python:3.13-slim

# espeak-ng: the local TTS provider (Phase 8, tts.py) — no cloud TTS key is
# available, so this is the real, working default. A cloud provider
# (ElevenLabs etc.) implementing the same TextToSpeech protocol removes
# this system dependency when one is added.
#
# Cache-mounted apt archives/lists: without this, every build re-downloads
# espeak-ng (and its dependencies) from the network even when nothing
# about this layer changed — the cache mount persists across builds the
# same way a real machine's local apt cache would, instead of starting
# from zero inside a fresh container every time.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends espeak-ng

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY shared/ shared/
COPY services/reachy-hub/ services/reachy-hub/
# The "Call Reachy" PWA (Phase 15) — reachy-hub serves it directly (ADR
# 0001: reachy-hub owns web UI), see app.py's StaticFiles mount.
COPY clients/web-pwa/ clients/web-pwa/
COPY clients/operator-ui/ clients/operator-ui/

# Cache-mounted uv/pip download cache: `uv sync` re-downloads every wheel
# from the index on every build without this — a source change in
# services/reachy-hub/ invalidates this layer (it always did, since
# `uv sync` needs to build this workspace member's own wheel from source),
# but the *download* half of the work is now cached across builds instead
# of re-fetched from the network each time.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package reachy-hub

EXPOSE 8000
# See reachy-embodiment/Dockerfile for why this calls the venv directly
# instead of `uv run`.
CMD ["/app/.venv/bin/uvicorn", "reachy_hub.main:app", "--app-dir", "services/reachy-hub/src", "--host", "0.0.0.0", "--port", "8000"]
