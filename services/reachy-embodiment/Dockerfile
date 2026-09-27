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
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgirepository1.0-dev gobject-introspection libcairo2-dev pkg-config gcc python3-dev \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    gstreamer1.0-alsa \
    libgstreamer1.0-0 gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gir1.2-glib-2.0 \
    && rm -rf /var/lib/apt/lists/* \
    # plugins-bad's ONNX plugin dies with SIGILL while the registry is
    # scanned on the Nano's ARMv8.0 Cortex-A57, killing the whole process at
    # Gst.init(). No element we use comes from it.
    && rm -f /usr/lib/*/gstreamer-1.0/libgstonnx.so

RUN pip install --no-cache-dir uv

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

# The SDK hardcodes the daemon's camera socket at this path. On the Nano,
# scripts/start-reachy.sh binds the host's /tmp at /host-tmp so the link
# follows the socket the daemon recreates on every media start; elsewhere
# it dangles harmlessly.
RUN ln -s /host-tmp/reachymini_camera_socket /tmp/reachymini_camera_socket

# Phase 24g: the community "Hey Reachy" Edge Impulse keyword model
# (BSD-3-Clause-Clear project, CC0 data), a native runner executable the
# wake monitor drives over a Unix socket. Pinned to one Space revision and
# checksummed like the hub's models; the app picks the file named for
# platform.machine(). Benchmarked on nano-1 in
# docs/verification/phase-24g-detector-bench-2026-09-27.md.
ADD --chmod=755 --checksum=sha256:9861b8d43bd9a2b95bf0105262d358c9f6b5aa17fa0b266b0dadae8328c3f229 \
    https://huggingface.co/spaces/luisomoreau/hey_reachy_wake_word_detection/resolve/3b6670748dc3ffda9f09dce18810b283ace7147e/hey_reachy_wake_word_detection/models/hey-reachy-wake-word-detection-linux-aarch64.eim \
    /opt/wake/hey-reachy-aarch64.eim
ADD --chmod=755 --checksum=sha256:d861eaa1cf6a329150f6caf4181d7c03e1eecbfe52fbc5ce2334907a5eb708dd \
    https://huggingface.co/spaces/luisomoreau/hey_reachy_wake_word_detection/resolve/3b6670748dc3ffda9f09dce18810b283ace7147e/hey_reachy_wake_word_detection/models/hey-reachy-wake-word-detection-linux-x86_64.eim \
    /opt/wake/hey-reachy-x86_64.eim

EXPOSE 8000
# Invoke the venv's uvicorn directly rather than `uv run` — `uv run` would
# re-check/sync the project (including pulling dev dependencies) on every
# container start, requiring network access at boot for no reason; the venv
# built above already has everything this service needs.
CMD ["/app/.venv/bin/uvicorn", "reachy_embodiment.app:app", "--app-dir", "services/reachy-embodiment/src", "--host", "0.0.0.0", "--port", "8000"]
