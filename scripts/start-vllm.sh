#!/usr/bin/env bash
# Start, stop or inspect the vLLM model server (compose service `vllm`,
# profile `vllm`). It never stops other GPU users: if free VRAM is too low it
# lists the holders and exits.
#
# Usage: scripts/start-vllm.sh [--env-file PATH] [--check] [--status] [--stop]
#                              [--model HF_ID] [--min-free-mib N] [--timeout S] [--help]
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

COMPOSE_DIR="${SCRIPT_DIR}/../deploy/homelab"
PROJECT_NAME="reachy-homelab"
ACTION=start
MIN_FREE_MIB=12500
WAIT_TIMEOUT=900
MODEL=""

print_help() {
    cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [options]

Starts the vLLM server (default model Qwen/Qwen2.5-7B-Instruct-AWQ, or
VLLM_MODEL from the env file) and waits for it to serve /v1/models.

  --status          Show container state and GPU memory; change nothing.
  --stop            Stop and remove only the vllm container.
  --model HF_ID     Override VLLM_MODEL for this run.
  --min-free-mib N  Refuse to start with less free VRAM (default $MIN_FREE_MIB).
  --timeout S       Seconds to wait for readiness (default $WAIT_TIMEOUT).
EOF
    print_common_help
}

parse_common_args "$@"
set -- "${COMMON_REMAINING_ARGS[@]+"${COMMON_REMAINING_ARGS[@]}"}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --status) ACTION=status ;;
        --stop) ACTION=stop ;;
        --model) [[ $# -ge 2 ]] || die "--model requires a value"; MODEL="$2"; shift ;;
        --min-free-mib) [[ $# -ge 2 ]] || die "--min-free-mib requires a value"; MIN_FREE_MIB="$2"; shift ;;
        --timeout) [[ $# -ge 2 ]] || die "--timeout requires a value"; WAIT_TIMEOUT="$2"; shift ;;
        --help) print_help; exit 0 ;;
        *) die "unknown argument: $1 (see --help)" ;;
    esac
    shift
done
[[ "$MIN_FREE_MIB" =~ ^[0-9]+$ && "$WAIT_TIMEOUT" =~ ^[0-9]+$ ]] || die "--min-free-mib and --timeout must be integers"

ENV_FILE="${COMMON_ENV_FILE:-${COMPOSE_DIR}/.env}"
[[ -f "$ENV_FILE" ]] || die "env file not found: $ENV_FILE"
if [[ -z "${SEARXNG_SECRET_KEY:-}" && -f "${COMPOSE_DIR}/.env.searxng-secret" ]]; then
    SEARXNG_SECRET_KEY="$(cat "${COMPOSE_DIR}/.env.searxng-secret")"
fi
# Compose only needs a value to interpolate the file; --check must not write one.
export SEARXNG_SECRET_KEY="${SEARXNG_SECRET_KEY:-check-only-placeholder}"
[[ -z "$MODEL" ]] || export VLLM_MODEL="$MODEL"

require_cmd docker "Install Docker with the NVIDIA container toolkit."
COMPOSE=(docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" --profile vllm)
cd "$COMPOSE_DIR"

gpu_free_mib() {
    local used total
    IFS=, read -r used total < <(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | head -n1)
    echo $(( ${total// /} - ${used// /} ))
}

gpu_holders() {
    docker ps --format '{{.Names}} ({{.Image}})' | grep -i -E 'vllm|ovms|llama' || true
}

port="${VLLM_HOST_PORT:-8003}"

case "$ACTION" in
    status)
        "${COMPOSE[@]}" ps vllm || true
        command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
        exit 0
        ;;
    stop)
        "${COMPOSE[@]}" rm -sf vllm
        exit 0
        ;;
esac

"${COMPOSE[@]}" config --quiet || die "compose config is invalid"
require_cmd nvidia-smi "The NVIDIA driver is required."
free="$(gpu_free_mib)"
log_info "free VRAM: ${free} MiB (need ${MIN_FREE_MIB})"
if (( free < MIN_FREE_MIB )); then
    log_error "not enough free VRAM; GPU containers that may hold it:"
    gpu_holders >&2
    die "stop the holder yourself (this script never does) and rerun"
fi
if [[ "$COMMON_CHECK_ONLY" -eq 1 ]]; then
    log_info "--check complete, nothing was started"
    exit 0
fi

"${COMPOSE[@]}" up -d vllm
wait_for_http "http://127.0.0.1:${port}/v1/models" "$WAIT_TIMEOUT" 5 \
    || die "vllm not ready; see: docker compose -p $PROJECT_NAME logs vllm"
log_info "vllm ready. Point the local provider at http://vllm:8000/v1 (Settings > LLM)."
