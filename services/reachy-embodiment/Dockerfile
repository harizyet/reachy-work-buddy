# syntax=docker/dockerfile:1
# The syntax pragma above opts into BuildKit's Dockerfile frontend, which
# `--mount=type=cache` below requires — building this file needs BuildKit
# (the `docker buildx` CLI plugin; see AGENTS.md's Dev setup section for
# how to install it without root if it's missing).
#
# Reference image for local/dev integration testing (deploy/homelab's
# docker-compose.yml runs this alongside companion-core and reachy-hub so
# the full chain can be smoke-tested with one `docker compose up`).
#
# In production, reachy-embodiment runs on the Reachy Mini itself (see
# deploy/reachy/), not in the homelab compose stack — this image is not
# used there.
FROM python:3.13-slim

# Phase 22b camera refactor: PyGObject (the `gi` bindings `reachy_mini`'s
# LOCAL media backend needs) has no PyPI wheel and builds from source, so
# its build deps (libgirepository/libcairo/pkg-config/gcc/python3-dev) are
# needed even though only the resulting .so is used at runtime. The
# gstreamer1.0-plugins-bad package is what actually ships `unixfdsrc`, the
# element that reads the daemon's local IPC camera socket — confirmed
# present at 1.26.2 on this same base image (Debian trixie), which is
# above the >=1.24 floor the daemon's own media_server requires.
# The SDK also calls gi.require_version for GstApp and GstPbutils, which
# only gir1.2-gst-plugins-base-1.0 ships; without it every LOCAL client
# fails with "Namespace GstApp not available" (found live on nano-1, 24d).
# Debian packages alsasrc/alsasink, used for the .asoundrc voice devices,
# separately in gstreamer1.0-alsa.
# libgles2: MediaPipe's native library links libGLESv2.so.2 even for CPU
# inference (open-palm stop, Phase 24e item 5); found by building this
# image, where it failed to load without it.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgirepository1.0-dev gobject-introspection libcairo2-dev pkg-config gcc python3-dev \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    gstreamer1.0-alsa libgles2 \
    libgstreamer1.0-0 gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gir1.2-glib-2.0 \
    && rm -rf /var/lib/apt/lists/* \
    # plugins-bad's ONNX plugin dies with SIGILL while the registry is
    # scanned on the Nano's ARMv8.0 Cortex-A57, killing the whole process at
    # Gst.init(). No element we use comes from it.
    && rm -f /usr/lib/*/gstreamer-1.0/libgstonnx.so

RUN pip install --no-cache-dir uv

# Phase 24e item 5: MediaPipe gesture model for open-palm stop, used only
# with PALM_STOP_ENABLED=true. Versioned URL plus SHA-256 pin, so a changed
# upstream file fails the build instead of silently changing detection.
RUN python - <<'EOF'
import hashlib, pathlib, urllib.request
url = "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
expected = "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482"
data = urllib.request.urlopen(url, timeout=60).read()
actual = hashlib.sha256(data).hexdigest()
if actual != expected:
    raise SystemExit(f"gesture model checksum mismatch: {actual}")
path = pathlib.Path("/opt/models/gesture_recognizer.task")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_bytes(data)
EOF

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY shared/ shared/
COPY services/reachy-embodiment/ services/reachy-embodiment/

# Cache-mounted uv/pip download cache — this service pulls in torch/
# torchaudio (see pyproject.toml's comment on them), by far the heaviest
# download in this whole repo; without this mount, every build re-fetches
# those CPU wheels from the network from scratch even when nothing in
# services/reachy-embodiment/ actually touches them.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package reachy-embodiment

EXPOSE 8000
# Invoke the venv's uvicorn directly rather than `uv run` — `uv run` would
# re-check/sync the project (including pulling dev dependencies) on every
# container start, requiring network access at boot for no reason; the venv
# built above already has everything this service needs.
CMD ["/app/.venv/bin/uvicorn", "reachy_embodiment.app:app", "--app-dir", "services/reachy-embodiment/src", "--host", "0.0.0.0", "--port", "8000"]
