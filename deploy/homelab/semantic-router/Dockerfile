# Shadow semantic router sidecar (docs/shadow-router.md). The ONNX models are NOT in the image or the repo:
# they are mounted read-only at /app/models (see this directory's README).
FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" onnxruntime numpy transformers tokenizers pydantic
WORKDIR /app
COPY app/ app/
EXPOSE 8012
USER 1000:1000
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8012", "--no-access-log"]
