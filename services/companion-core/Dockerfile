FROM python:3.13-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY shared/ shared/
COPY services/companion-core/ services/companion-core/

RUN uv sync --frozen --no-dev --package companion-core

EXPOSE 8000
# See reachy-embodiment/Dockerfile for why this calls the venv directly
# instead of `uv run`.
CMD ["/app/.venv/bin/uvicorn", "companion_core.main:app", "--app-dir", "services/companion-core/src", "--host", "0.0.0.0", "--port", "8000"]
