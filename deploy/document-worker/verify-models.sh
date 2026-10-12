#!/bin/sh
# Check the model files against the recorded hashes (models.sha256, from the verified 50A download). Read-only.
# Usage: ./verify-models.sh [models-dir]   (default: DOCUMENT_WORKER_MODELS_DIR from .env)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
dir=${1:-}
if [ -z "$dir" ] && [ -f "$here/.env" ]; then dir=$(sed -n 's/^DOCUMENT_WORKER_MODELS_DIR=//p' "$here/.env" | tail -n 1); fi
[ -n "$dir" ] && [ -d "$dir" ] || { echo "models directory not given or missing" >&2; exit 2; }
cd "$dir" && sha256sum --check --quiet "$here/models.sha256" && echo "models: all $(wc -l < "$here/models.sha256") files match"
