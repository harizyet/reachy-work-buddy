#!/usr/bin/env bash
# Start on the original Jetson Nano companion board. Per Phase 22's
# topology decision (docs/adr/0004-offline-fallback.md's "Phase 22
# topology amendment" and docs/phase-22-23.md), this specific deployment
# has no separate "Reachy onboard computer" — the Nano IS the confirmed
# embodiment host — so after its own Nano-specific checks, this script
# delegates the actual embodiment startup to start-reachy.sh, per
# phase-22-23.md's launcher contract: "delegate to the Reachy launcher
# only if the topology decision explicitly assigns that role."
#
# Usage: scripts/start-jetson.sh [--env-file PATH] [--no-browser] [--check]
#                                 [--help] [any start-reachy.sh option]
# Unrecognized options are passed through to start-reachy.sh unchanged.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

REACHY_DIR="${SCRIPT_DIR}/../deploy/reachy"
DEFAULT_ENV_FILE="${REACHY_DIR}/.env"
INVENTORY_DOC="${SCRIPT_DIR}/../docs/verification/phase-22-inventory-2026-09-22.md"

print_help() {
    cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [options]

Nano-specific readiness checks (compatibility baseline, network/hub
reachability), then delegates to scripts/start-reachy.sh — this
deployment's topology decision makes the Nano the embodiment host
itself, not a separate companion board. See:
  ${INVENTORY_DOC}

Any option not listed below is passed through to start-reachy.sh.
EOF
    print_common_help
}

parse_common_args "$@"
REMAINING=("${COMMON_REMAINING_ARGS[@]}")
PASSTHROUGH_ARGS=()
i=0
while [[ $i -lt ${#REMAINING[@]} ]]; do
    arg="${REMAINING[$i]}"
    case "$arg" in
        --help) print_help; exit 0 ;;
        *) PASSTHROUGH_ARGS+=("$arg") ;;
    esac
    i=$((i + 1))
done

ENV_FILE="${COMMON_ENV_FILE:-$DEFAULT_ENV_FILE}"

# --- 1. compatibility baseline sanity check (non-fatal) ---------------------
# Full inventory was a one-time manual process (see the doc above); this
# is a cheap live sanity check that this is still recognizably the same
# board, not a re-run of that whole process.
if [[ -r /proc/device-tree/model ]]; then
    MODEL="$(tr -d '\0' < /proc/device-tree/model || true)"
    log_info "board: $MODEL"
    [[ "$MODEL" == *"Jetson Nano"* ]] || log_warn "this doesn't look like a Jetson Nano ('$MODEL') — the recorded compatibility baseline may not apply"
else
    log_warn "/proc/device-tree/model not readable — cannot confirm this is the inventoried Jetson Nano"
fi
if [[ -r /etc/nv_tegra_release ]]; then
    log_info "L4T release: $(tr -d '\n' < /etc/nv_tegra_release)"
else
    log_warn "/etc/nv_tegra_release not found — cannot confirm the recorded JetPack version"
fi

# --- 2. network/hub reachability (non-fatal, informational) ----------------
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    HUB_URL_PREVIEW="$(grep -E '^HUB_WS_URL=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"
    if [[ -n "$HUB_URL_PREVIEW" ]]; then
        HUB_HEALTH_URL="${HUB_URL_PREVIEW}/health"
        if curl -fsS -o /dev/null --max-time 5 "$HUB_HEALTH_URL" 2>/dev/null; then
            log_info "hub reachable at $HUB_URL_PREVIEW"
        else
            log_warn "hub not reachable at $HUB_URL_PREVIEW right now — start-reachy.sh's WS client will retry with backoff once it starts, this is not fatal"
        fi
    fi
fi

# --- 3. delegate to start-reachy.sh -----------------------------------------
# The supervised container (start-reachy.sh's docker run --restart
# unless-stopped) owns reconnection from here — this script does not loop
# or stay foreground, per phase-22-23.md: "The supervised service owns
# reconnection, not a foreground shell loop."
log_info "delegating to start-reachy.sh (this Nano is the confirmed embodiment host)"
DELEGATE_ARGS=(--env-file "$ENV_FILE")
[[ "$COMMON_NO_BROWSER" -eq 1 ]] && DELEGATE_ARGS+=(--no-browser)
[[ "$COMMON_CHECK_ONLY" -eq 1 ]] && DELEGATE_ARGS+=(--check)
exec "${SCRIPT_DIR}/start-reachy.sh" "${DELEGATE_ARGS[@]}" "${PASSTHROUGH_ARGS[@]}"
