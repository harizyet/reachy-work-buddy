#!/usr/bin/env bash
# Start real embodiment on the confirmed embodiment host — checks the
# reachy-mini-daemon is up and not simulated, then runs reachy-embodiment
# in a container against it, establishing the ADR 0019 WSS connection to
# the hub. See docs/phase-22-23.md's "Bash launcher contract" and
# docs/verification/phase-22-inventory-2026-09-22.md for why a container
# (not a native venv) and why device passthrough works the way it does
# below — both were verified live on the Jetson Nano during Phase 22.
#
# HONEST LIMITATION (see deploy/reachy/.env.example and HANDOVER.md): the
# ADR 0019 WSS connection this script establishes is connectivity/liveness
# only as of this writing. Real commands (behaviour/camera/audio) still
# go over the old HTTP EmbodimentClient path, which is why this script
# also still registers an HTTP base_url with the hub the old way — this
# is a real, temporary contradiction of ADR 0019's "no inbound robot
# ports" goal, not yet resolved. Remove that registration once command
# routing moves onto the WSS connection, not before.
#
# Usage: scripts/start-reachy.sh [--env-file PATH] [--no-browser] [--check]
#                                 [--build] [--image NAME] [--port PORT]
#                                 [--help]
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

REPO_ROOT="${SCRIPT_DIR}/.."
REACHY_DIR="${SCRIPT_DIR}/../deploy/reachy"
DEFAULT_ENV_FILE="${REACHY_DIR}/.env"
IMAGE_NAME="reachy-embodiment:local"
CONTAINER_NAME="reachy-embodiment"
HTTP_PORT=8000
DO_BUILD=0
DAEMON_SERVICE="reachy-mini-daemon"
DAEMON_READY_TIMEOUT=60

print_help() {
    cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [options]

Starts real reachy-embodiment on this host: verifies reachy-mini-daemon
(deploy/reachy/reachy-mini-daemon.service) is active and not simulated,
then runs reachy-embodiment in a container against it, with the device
passthrough and generation verified during Phase 22's Nano bring-up.

Options:
  --build           Rebuild the reachy-embodiment image before starting.
  --image NAME      Image tag to run (default: ${IMAGE_NAME}).
  --port PORT       Host port for reachy-embodiment's HTTP API (default: ${HTTP_PORT}).
EOF
    print_common_help
}

parse_common_args "$@"
REMAINING=("${COMMON_REMAINING_ARGS[@]}")
i=0
while [[ $i -lt ${#REMAINING[@]} ]]; do
    arg="${REMAINING[$i]}"
    case "$arg" in
        --build) DO_BUILD=1 ;;
        --image)
            i=$((i + 1)); [[ $i -lt ${#REMAINING[@]} ]] || die "--image requires a name argument"
            IMAGE_NAME="${REMAINING[$i]}"
            ;;
        --image=*) IMAGE_NAME="${arg#--image=}" ;;
        --port)
            i=$((i + 1)); [[ $i -lt ${#REMAINING[@]} ]] || die "--port requires a value"
            HTTP_PORT="${REMAINING[$i]}"
            ;;
        --port=*) HTTP_PORT="${arg#--port=}" ;;
        --help) print_help; exit 0 ;;
        *) die "unknown argument: $arg (see --help)" ;;
    esac
    i=$((i + 1))
done

ENV_FILE="${COMMON_ENV_FILE:-$DEFAULT_ENV_FILE}"
[[ -f "$ENV_FILE" ]] || die "env file not found: $ENV_FILE (copy deploy/reachy/.env.example to .env and fill it in, or pass --env-file)"
load_env_file "$ENV_FILE"

for var in HUB_WS_URL ROBOT_ID ROBOT_TOKEN; do
    [[ -n "${!var:-}" ]] || die "$var must be set in $ENV_FILE (see deploy/reachy/.env.example)"
done
: "${ROBOT_BACKEND:=reachy_daemon}"
: "${REACHY_DAEMON_URL:=http://host.docker.internal:8000}"

# --- 1. confirm this is the embodiment host, daemon is up, not simulated ---
require_cmd systemctl "reachy-mini-daemon is supervised via systemd — see deploy/reachy/README.md for install steps."
if ! systemctl list-unit-files "${DAEMON_SERVICE}.service" >/dev/null 2>&1; then
    die "${DAEMON_SERVICE}.service is not installed. This is a first-time install step, not something this launcher does automatically — see deploy/reachy/install-reachy-venv.sh and reachy-mini-daemon.service, and deploy/reachy/README.md."
fi

if systemctl is-active --quiet "$DAEMON_SERVICE"; then
    log_info "$DAEMON_SERVICE already active"
else
    log_info "starting $DAEMON_SERVICE"
    sudo systemctl start "$DAEMON_SERVICE" || die "failed to start $DAEMON_SERVICE — check: systemctl status $DAEMON_SERVICE"
fi

DAEMON_STATUS_URL="http://127.0.0.1:8000/daemon/status"
wait_for_http "$DAEMON_STATUS_URL" "$DAEMON_READY_TIMEOUT" \
    || die "reachy-mini-daemon did not become ready — check: systemctl status $DAEMON_SERVICE; journalctl -u $DAEMON_SERVICE"

DAEMON_STATUS_JSON="$(curl -fsS "$DAEMON_STATUS_URL")" || die "could not read daemon status after it reported ready"
SIM_ENABLED="$(printf '%s' "$DAEMON_STATUS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("simulation_enabled") or d.get("mockup_sim_enabled") or False)' 2>/dev/null || echo "unknown")"
if [[ "$SIM_ENABLED" == "True" ]]; then
    die "reachy-mini-daemon reports simulation_enabled/mockup_sim_enabled=true — this script is for REAL hardware. Restart the daemon without --sim/--mockup-sim, or use the homelab's --simulation workflow instead of this script."
elif [[ "$SIM_ENABLED" == "unknown" ]]; then
    log_warn "could not parse daemon status to confirm sim=false (no python3, or unexpected response shape) — proceeding, but verify manually: curl $DAEMON_STATUS_URL"
else
    log_info "confirmed real hardware: daemon simulation flags are false"
fi

if [[ "$COMMON_CHECK_ONLY" -eq 1 ]]; then
    log_info "--check complete: daemon is active and reports real hardware. Nothing else was started."
    exit 0
fi

# --- 2. build/run reachy-embodiment against the daemon ---------------------
if [[ "$DO_BUILD" -eq 1 ]]; then
    log_info "building $IMAGE_NAME"
    (cd "$REPO_ROOT" && docker build -f services/reachy-embodiment/Dockerfile -t "$IMAGE_NAME" .)
elif ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    die "$IMAGE_NAME not found locally — run with --build first (first-time install; routine restarts don't need it)"
fi

# Device/group setup verified live on the Jetson Nano during Phase 22 (see
# docs/verification/phase-22-inventory-2026-09-22.md's non-root device
# passthrough section): --group-add by numeric GID, not a matching named
# user inside the image, is sufficient and correctly gated.
DEVICE_ARGS=()
GROUP_ARGS=()
for dev in /dev/video0 /dev/ttyACM0; do
    if [[ -e "$dev" ]]; then
        DEVICE_ARGS+=(--device "$dev")
    else
        log_warn "$dev not found — camera/serial capability may be unavailable"
    fi
done
if [[ -d /dev/snd ]]; then
    DEVICE_ARGS+=(--device /dev/snd)
else
    log_warn "/dev/snd not found — audio capability may be unavailable"
fi
for grp in dialout video audio; do
    gid="$(getent group "$grp" 2>/dev/null | cut -d: -f3 || true)"
    if [[ -n "$gid" ]]; then
        GROUP_ARGS+=(--group-add "$gid")
    else
        log_warn "group '$grp' not found on this host"
    fi
done

# Idempotent: starting twice must be safe (phase-22-23.md). An existing
# stopped container is restarted, not duplicated; an already-running one
# is left alone.
if docker ps --filter "name=^/${CONTAINER_NAME}\$" --filter status=running -q | grep -q .; then
    log_info "$CONTAINER_NAME is already running"
else
    if docker ps -a --filter "name=^/${CONTAINER_NAME}\$" -q | grep -q .; then
        log_info "restarting existing $CONTAINER_NAME container"
        docker start "$CONTAINER_NAME" >/dev/null
    else
        log_info "starting $CONTAINER_NAME (port $HTTP_PORT, real backend, WSS to $HUB_WS_URL)"
        docker run -d --name "$CONTAINER_NAME" --restart unless-stopped \
            --add-host host.docker.internal:host-gateway \
            -p "${HTTP_PORT}:8000" \
            -e "ROBOT_BACKEND=${ROBOT_BACKEND}" \
            -e "REACHY_DAEMON_URL=${REACHY_DAEMON_URL}" \
            -e "HUB_WS_URL=${HUB_WS_URL}" \
            -e "ROBOT_ID=${ROBOT_ID}" \
            -e "ROBOT_TOKEN=${ROBOT_TOKEN}" \
            "${DEVICE_ARGS[@]}" "${GROUP_ARGS[@]}" \
            "$IMAGE_NAME" >/dev/null
    fi
fi

wait_for_http "http://127.0.0.1:${HTTP_PORT}/health" 60 || die "reachy-embodiment did not become healthy — check: docker logs $CONTAINER_NAME"
log_info "reachy-embodiment is up (sim=false, connected to daemon and attempting hub WSS registration)"

# --- 3. bridge registration (see HONEST LIMITATION note at the top) --------
if [[ -n "${ROBOT_HTTP_BASE_URL:-}" ]]; then
    log_info "registering HTTP base_url with hub (still the real command path — see this script's header comment)"
    if curl -fsS -X POST "${HUB_WS_URL}/robots" \
        -H 'Content-Type: application/json' \
        -d "{\"robot_id\": \"${ROBOT_ID}\", \"base_url\": \"${ROBOT_HTTP_BASE_URL}\"}" \
        >/dev/null; then
        log_info "registered ${ROBOT_ID} -> ${ROBOT_HTTP_BASE_URL} with hub"
    else
        log_warn "hub HTTP registration failed — commands from companion-core won't reach this robot yet. Check the hub is reachable at ${HUB_WS_URL}."
    fi
else
    log_warn "ROBOT_HTTP_BASE_URL is not set — skipping legacy hub registration. Real commands will not reach this robot until command routing moves onto the WSS connection, or this is set (see deploy/reachy/.env.example)."
fi

open_browser_or_print "${HUB_WS_URL}/ui/"
