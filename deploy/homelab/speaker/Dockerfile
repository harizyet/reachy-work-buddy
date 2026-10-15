# Speaker embeddings for shared voice identity (Phase 32A.V, ADR 0041). CPU-only
# SpeechBrain ECAPA-TDNN, the model measured in Phase 25a.1. Stateless: it keeps no
# audio or embedding. reachy-hub owns profiles, consent and decisions.
FROM python:3.12-slim
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir "speechbrain==1.1.1" huggingface_hub numpy fastapi "uvicorn[standard]" python-multipart
COPY app /app
WORKDIR /app
# HF_HOME under /data (the speaker-data volume) so the pinned model survives a recreate.
ENV HF_HOME=/data/hf PYTHONUNBUFFERED=1
EXPOSE 8012
ENTRYPOINT ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8012"]
