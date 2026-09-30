# Nemotron-3-Diarization (NeMo Sortformer) with its per-chunk network step
# running on OpenVINO — Intel iGPU by default, CPU as a fallback. Ported
# from local experimentation (previously tested standalone, not part of
# this repo) into Phase 27.3 (docs/phase-27.md); companion-core does not
# yet call this service (see docs/phase-27.md's Status section).
#
# Base image = OpenVINO Model Server GPU build: it already carries the
# Intel GPU compute runtime (Level Zero / OpenCL / IGC); we only add
# Python, NeMo (streaming state logic) and this HTTP wrapper.
FROM openvino/model_server:latest-gpu
USER root
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_LINK_MODE=copy VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
RUN uv venv --python 3.12 /opt/venv \
 && uv pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && uv pip install Cython packaging
# NeMo main, pinned: the released 3.0.0 cannot load this model (needs 'rope' attention support).
RUN uv pip install "nemo-toolkit[asr] @ https://github.com/NVIDIA-NeMo/NeMo/archive/cf724ac337d1ebc7d0dda1e23fb80916f52927a5.tar.gz" \
 && uv pip install openvino fastapi "uvicorn[standard]" python-multipart
COPY app /app
WORKDIR /app
# HF_HOME/HOME/ONNX_PATH all live under /data (the diarization-data volume,
# see docker-compose.yml) so the downloaded model weights and the
# exported ONNX graph survive a container recreate — the first start
# downloads and exports (~1 min), later starts reuse both.
ENV HF_HOME=/data/hf HOME=/data/home PYTHONUNBUFFERED=1 ONNX_PATH=/data/sortformer_step.onnx
EXPOSE 8010
ENTRYPOINT ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8010"]
