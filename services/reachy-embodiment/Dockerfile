# Reference image for local/dev integration testing (deploy/homelab's
# docker-compose.yml runs this alongside companion-core and reachy-hub so
# the full chain can be smoke-tested with one `docker compose up`).
#
# In production, reachy-embodiment runs on the Reachy Mini itself (see
# deploy/reachy/), not in the homelab compose stack — this image is not
# used there.
FROM python:3.13-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY shared/ shared/
COPY services/reachy-embodiment/ services/reachy-embodiment/

RUN uv sync --frozen --no-dev --package reachy-embodiment

EXPOSE 8000
# Invoke the venv's uvicorn directly rather than `uv run` — `uv run` would
# re-check/sync the project (including pulling dev dependencies) on every
# container start, requiring network access at boot for no reason; the venv
# built above already has everything this service needs.
CMD ["/app/.venv/bin/uvicorn", "reachy_embodiment.app:app", "--app-dir", "services/reachy-embodiment/src", "--host", "0.0.0.0", "--port", "8000"]
