FROM python:3.13-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY shared/ shared/
COPY services/reachy-hub/ services/reachy-hub/

RUN uv sync --frozen --no-dev --package reachy-hub

EXPOSE 8000
# See reachy-embodiment/Dockerfile for why this calls the venv directly
# instead of `uv run`.
CMD ["/app/.venv/bin/uvicorn", "reachy_hub.main:app", "--app-dir", "services/reachy-hub/src", "--host", "0.0.0.0", "--port", "8000"]
