#!/usr/bin/env bash
# Run the model manager (Phase 42B, ADR 0031) as a HOST process on 127.0.0.1.
# It stops and starts the vLLM containers, so it uses the owner's own Docker
# access rather than a socket mounted into another container. Manual operation
# only: nothing calls it automatically yet.
#
# Usage: scripts/start-model-manager.sh [--check] [--port N] [--bridge] [--help]
#   --bridge  Also listen on the Docker bridge address (docker0), which containers
#             such as companion-core reach as host.docker.internal but the LAN does not.
#             Needed for the Deep Local feature (Phase 42C); the token still applies.
#   --check   Read-only: validates the config and Docker access, writes nothing,
#             starts nothing, and never prints the token.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

REPO_ROOT="${SCRIPT_DIR}/.."
TOKEN_FILE="${REPO_ROOT}/deploy/homelab/.env.model-manager"  # MODEL_MANAGER_TOKEN=..., also read by compose for companion-core
PORT=8090
BRIDGE=0

print_help() {
    sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    print_common_help
}

parse_common_args "$@"
set -- "${COMMON_REMAINING_ARGS[@]+"${COMMON_REMAINING_ARGS[@]}"}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) [[ $# -ge 2 ]] || die "--port requires a value"; PORT="$2"; shift ;;
        --bridge) BRIDGE=1 ;;
        --help) print_help; exit 0 ;;
        *) die "unknown argument: $1 (see --help)" ;;
    esac
    shift
done
[[ "$PORT" =~ ^[0-9]+$ ]] || die "--port must be an integer"

require_cmd docker "Install Docker with the NVIDIA container toolkit."
require_cmd uv "Install uv (docs/development.md)."
cd "$REPO_ROOT"

if [[ "$COMMON_CHECK_ONLY" -eq 1 ]]; then
    docker info >/dev/null 2>&1 || die "cannot talk to the Docker daemon"
    log_info "docker: ok"
    if [[ -f "$TOKEN_FILE" ]]; then
        [[ "$(stat -c %a "$TOKEN_FILE")" == "600" ]] || log_warn "$TOKEN_FILE should be mode 600"
        log_info "token file: present"
    else
        log_info "token file: absent (a start would create it, mode 600)"
    fi
    uv run --package model-manager python -c "from model_manager.config import load_config; c = load_config(); print('config ok: t1', c.t1.model, '| t2', c.t2.model, '| name', c.served_model_name)"
    exit 0
fi

if [[ ! -f "$TOKEN_FILE" ]]; then
    require_cmd openssl "Install openssl."
    log_info "creating the manager token (deploy/homelab/.env.model-manager, mode 600)"
    ( umask 177 && printf 'MODEL_MANAGER_TOKEN=%s\n' "$(openssl rand -hex 32)" > "$TOKEN_FILE" )
fi
export MODEL_MANAGER_TOKEN
MODEL_MANAGER_TOKEN="$(sed -n 's/^MODEL_MANAGER_TOKEN=//p' "$TOKEN_FILE" | head -n1)"
HOST=127.0.0.1
if [[ "$BRIDGE" -eq 1 ]]; then
    HOST="$(ip -4 -o addr show docker0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1)"
    [[ -n "$HOST" ]] || die "no docker0 address found for --bridge"
fi
log_info "model manager on http://${HOST}:${PORT} (token in deploy/homelab/.env.model-manager)"
exec uv run --package model-manager python -m model_manager serve --port "$PORT" --host "$HOST"
