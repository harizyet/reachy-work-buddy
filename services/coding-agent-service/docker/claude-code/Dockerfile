# Phase 29.3 (docs/phase-29.md): the agent container a real session runs
# in. This is NOT coding-agent-service's own image (../../Dockerfile) —
# it's what DockerCLIContainerRuntime starts per session, with the
# project mounted at /workspace and ANTHROPIC_API_KEY injected from the
# owner-entered credential (29.19), never baked into this image.
FROM node:20-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

WORKDIR /workspace

# node:20-slim's built-in "node" user is uid/gid 1000, matching
# DockerCLIContainerRuntime's default --user "1000:1000" (runtime.py) — no
# extra useradd needed, and no container here ever runs as root.
USER node

ENTRYPOINT ["claude"]
