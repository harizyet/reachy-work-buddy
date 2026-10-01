FROM python:3.13-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY shared/ shared/
COPY services/coding-agent-service/ services/coding-agent-service/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package coding-agent-service

EXPOSE 8000
# Invoke the venv's uvicorn directly rather than `uv run` — see
# services/reachy-embodiment/Dockerfile's comment for why.
CMD ["/app/.venv/bin/uvicorn", "coding_agent_service.app:app", "--app-dir", "services/coding-agent-service/src", "--host", "0.0.0.0", "--port", "8000"]
