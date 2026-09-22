# syntax=docker/dockerfile:1
# The syntax pragma above opts into BuildKit's Dockerfile frontend, which
# `--mount=type=cache` below requires — building this file needs BuildKit
# (the `docker buildx` CLI plugin; see AGENTS.md's Dev setup section for
# how to install it without root if it's missing).
FROM python:3.13-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY shared/ shared/
COPY services/companion-core/ services/companion-core/

# Cache-mounted uv/pip download cache — see reachy-hub/Dockerfile's
# comment on the same mount for why.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package companion-core

EXPOSE 8000
# See reachy-embodiment/Dockerfile for why this calls the venv directly
# instead of `uv run`.
CMD ["/app/.venv/bin/uvicorn", "companion_core.main:app", "--app-dir", "services/companion-core/src", "--host", "0.0.0.0", "--port", "8000"]
