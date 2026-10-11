# Phase 50A: the document worker, i.e. the Reachy-safe adapter plus a self-hosted MinerU document library (ADR 0034).
# MinerU's dependency stack lives only in this image, from a hash-pinned lock (deploy/homelab/document-worker/); it
# never enters companion-core or the workspace lock. CPU only: the image has no GPU runtime and the env below also hides
# Vulkan, because MinerU's llama.cpp VLM is a Vulkan build that otherwise takes GPU memory beside the production LLM.
FROM python:3.13-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY shared/ shared/
COPY services/document-worker/ services/document-worker/
COPY deploy/homelab/document-worker/requirements-mineru.txt /tmp/requirements-mineru.txt

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package document-worker \
    && uv pip install --python /app/.venv/bin/python --require-hashes --no-deps -r /tmp/requirements-mineru.txt \
    && /app/.venv/bin/mineru --version

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin worker \
    && mkdir -p /data /models && chown worker /data

# Short MINERU_HOME: the library listens on a Unix socket under it and socket paths are limited to 108 bytes.
ENV PATH=/app/.venv/bin:$PATH \
    HOME=/data/home \
    MINERU_HOME=/data/mineru \
    MINERU_MODEL_SOURCE=local \
    HF_HUB_OFFLINE=1 \
    CUDA_VISIBLE_DEVICES="" \
    VK_LOADER_DRIVERS_DISABLE="*" \
    GGML_VK_VISIBLE_DEVICES="" \
    DOCUMENT_WORKER_WORK_DIR=/data/work

# The working directory must be writable: MinerU's managed parse server resolves its default upload dir against it
# (a read-only /app made it fail with "Directory '' is not writable").
WORKDIR /data
USER worker
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=60s \
    CMD python -c "import json,sys,urllib.request;sys.exit(0 if json.load(urllib.request.urlopen('http://localhost:8000/health')).get('ok') else 1)"
CMD ["/app/services/document-worker/entrypoint.sh"]
