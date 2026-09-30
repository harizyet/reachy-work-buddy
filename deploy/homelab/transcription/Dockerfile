# Long-form meeting transcription (Phase 27.2, ADR 0025). Same
# faster-whisper library reachy-hub's conversational stt.py uses, but a
# separate deployable service — see this repo's app/server.py header
# comment for why. CPU by default (int8, matching reachy-hub's own
# default); no OpenVINO/GPU base image is needed the way the diarization
# sidecar (deploy/homelab/diarization/) needs one for its Intel-iGPU
# path — faster-whisper's ctranslate2 backend runs directly on this slim
# Python image. MEETING_STT_DEVICE can be set to "cuda" only if this image
# is later rebuilt from a CUDA-enabled base; unset/"cpu" always works.
FROM python:3.12-slim
RUN pip install --no-cache-dir faster-whisper "fastapi" "uvicorn[standard]" python-multipart
COPY app /app
WORKDIR /app
# HF_HOME under /data (the transcription-data volume, see
# docker-compose.yml) so the downloaded model survives a container
# recreate — the first start downloads it once.
ENV HF_HOME=/data/hf PYTHONUNBUFFERED=1
EXPOSE 8011
ENTRYPOINT ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8011"]
