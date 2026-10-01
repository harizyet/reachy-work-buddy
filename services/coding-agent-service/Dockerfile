FROM python:3.13-slim

# 29.2: runtime.py's DockerCLIContainerRuntime shells out to this binary to
# start/stop/inspect session containers on the *host* Docker daemon (via
# the socket mounted below in compose) — this is the orchestrator
# container, not a sandboxed agent one, so this is a deliberate exception
# to 29.18's "no Docker socket" rule for the containers a session itself
# runs in. docker-cli (not docker.io) is the client-only package: no
# dockerd, nothing auto-starts, just the binary this process invokes.
RUN apt-get update && apt-get install -y --no-install-recommends docker-cli \
    && rm -rf /var/lib/apt/lists/*

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
