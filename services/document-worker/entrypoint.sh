#!/bin/sh
# MinerU takes a file lock inside its model directory even when every model is already present, so a read-only models
# mount cannot be its base dir. Link each model repo into a writable tmpfs directory instead: the weights stay read-only
# (a compromised parser cannot alter them) and only the lock files are written.
set -eu
mkdir -p /tmp/models
for repo in /models/*; do
    [ -e "$repo" ] && ln -sfn "$repo" "/tmp/models/$(basename "$repo")"
done
export MINERU_MODEL_BASE_DIR=/tmp/models
exec uvicorn document_worker.app:create_app --factory --app-dir /app/services/document-worker/src --host 0.0.0.0 --port 8000
