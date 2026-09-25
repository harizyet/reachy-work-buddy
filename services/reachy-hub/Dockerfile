# syntax=docker/dockerfile:1
# The syntax pragma above opts into BuildKit's Dockerfile frontend, which
# `--mount=type=cache` below requires — building this file needs BuildKit
# (the `docker buildx` CLI plugin; see AGENTS.md's Dev setup section for
# how to install it without root if it's missing).
FROM python:3.13-slim

# libgles2, libegl1: MediaPipe's native library (open-palm stop, Phase 24e
# item 5) links libGLESv2.so.2 and libEGL.so.1 even for CPU inference.
# Found by building images without them (the embodiment image got libEGL
# through GStreamer; this one does not).
#
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
    apt-get update && apt-get install -y --no-install-recommends espeak-ng libgles2 libegl1

RUN pip install --no-cache-dir uv

# Piper voice (tts.py's deployed default since Phase 24d; espeak-ng above
# stays as the fallback when PIPER_VOICE_MODEL is unset). Pinned to a
# piper-voices commit and checksummed, so a rebuild can't change the voice.
ARG PIPER_VOICES_REV=c10ece1aade47bb51c153c893d14e5bf8e5b7117
ADD --checksum=sha256:5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f \
    https://huggingface.co/rhasspy/piper-voices/resolve/${PIPER_VOICES_REV}/en/en_US/lessac/medium/en_US-lessac-medium.onnx \
    /opt/piper/en_US-lessac-medium.onnx
ADD --checksum=sha256:efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0 \
    https://huggingface.co/rhasspy/piper-voices/resolve/${PIPER_VOICES_REV}/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json \
    /opt/piper/en_US-lessac-medium.onnx.json
ENV PIPER_VOICE_MODEL=/opt/piper/en_US-lessac-medium.onnx

# Phase 24e item 5: MediaPipe gesture model for open-palm stop, used only
# with PALM_STOP_ENABLED=true. Versioned URL plus SHA-256 pin, so a changed
# upstream file fails the build instead of silently changing detection.
ADD --checksum=sha256:97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482 \
    https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task \
    /opt/models/gesture_recognizer.task

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
CMD ["/app/.venv/bin/uvicorn", "reachy_hub.main:app", "--app-dir", "services/reachy-hub/src", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
