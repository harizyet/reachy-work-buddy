#!/usr/bin/env bash
# Non-destructive readiness checks and a redacted diagnostic report for
# whichever host this runs on (homelab, embodiment host, or both — each
# section below skips itself if not applicable). Physical motion/audio is
# never attempted unless --test-hardware is explicitly passed, and even
# then this asks for interactive confirmation unless --yes is also given —
# see docs/phase-22-23.md's "Bash launcher contract" and this whole
# project's established caution around moving a real robot unsupervised
# (see HANDOVER.md's Phase 22 notes on daemon start / --wake-up-on-start).
#
# Usage: scripts/check-platform.sh [--env-file PATH] [--check] [--help]
#                                   [--test-hardware] [--yes]
# (--no-browser is accepted for interface consistency with the other
# launchers but has no effect here — this script never opens a browser.)
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

REPO_ROOT="${SCRIPT_DIR}/.."
HOMELAB_ENV="${REPO_ROOT}/deploy/homelab/.env"
REACHY_ENV="${REPO_ROOT}/deploy/reachy/.env"
TEST_HARDWARE=0
ASSUME_YES=0

print_help() {
    cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [options]

Runs non-destructive readiness checks for whichever role(s) this host
looks like it plays (homelab / embodiment host), and prints a redacted
diagnostic report — secret values are never printed, only whether each
is set.

Options:
  --test-hardware   Also attempt one bounded, safe named move/sound on the
                     real robot (embodiment host only). Requires interactive
                     confirmation unless --yes is also given. NEVER run this
                     without someone physically present and watching the robot.
  --yes             Skip the interactive confirmation for --test-hardware.
EOF
    print_common_help
}

parse_common_args "$@"
REMAINING=("${COMMON_REMAINING_ARGS[@]}")
i=0
while [[ $i -lt ${#REMAINING[@]} ]]; do
    arg="${REMAINING[$i]}"
    case "$arg" in
        --test-hardware) TEST_HARDWARE=1 ;;
        --yes) ASSUME_YES=1 ;;
        --help) print_help; exit 0 ;;
        *) die "unknown argument: $arg (see --help)" ;;
    esac
    i=$((i + 1))
done

echo "=== Phase 22 platform diagnostic report ==="
echo "generated: $(date -u -Iseconds)"
echo

# --- general host info -------------------------------------------------
echo "--- Host ---"
echo "uname: $(uname -a)"
if [[ -r /proc/device-tree/model ]]; then
    echo "device-tree model: $(tr -d '\0' < /proc/device-tree/model)"
fi
if [[ -r /etc/nv_tegra_release ]]; then
    echo "L4T release: $(tr -d '\n' < /etc/nv_tegra_release)"
fi
if command -v python3 >/dev/null 2>&1; then
    echo "python3: $(python3 --version 2>&1)"
else
    echo "python3: not found"
fi
echo "disk (/): $(df -h / 2>/dev/null | awk 'NR==2 {print $4" free of "$2" ("$5" used)"}')"
if command -v free >/dev/null 2>&1; then
    echo "memory: $(free -h | awk 'NR==2 {print $7" available of "$2}')"
fi
if command -v timedatectl >/dev/null 2>&1; then
    # `timedatectl show` (any form: `-p X`, `--property=X`) doesn't exist
    # at all on systemd 237 (Ubuntu 18.04/Bionic, the Jetson Nano's OS) —
    # `timedatectl: unrecognized option`/`Unknown operation show`, a hard
    # failure every time, not an occasionally-empty result. An earlier
    # version of this fix assumed the latter and used a bare, unguarded
    # command substitution to try `show` first — under this script's
    # `set -euo pipefail` (from common.sh), that failure killed the
    # entire script immediately, before printing anything past the
    # memory line, never even reaching the fallback below. Caught live
    # on the Nano. `timedatectl status`'s "System clock synchronized:"
    # line is what's actually portable here, so it's the only method now
    # — no fragile `show` attempt to guard in the first place.
    # `|| true` guards the whole pipeline: under `set -o pipefail` (from
    # common.sh), grep finding no match would otherwise fail this
    # substitution too — the exact class of bug just found above, so
    # guarding it explicitly here rather than assuming grep always matches.
    NTP_SYNC="$(timedatectl status 2>/dev/null | grep -i 'system clock synchronized' | awk -F': ' '{print $2}' || true)"
    echo "time sync: ${NTP_SYNC:-unknown}"
fi
echo

# --- Docker toolchain ---------------------------------------------------
echo "--- Docker toolchain ---"
if command -v docker >/dev/null 2>&1; then
    echo "docker: $(docker --version 2>&1)"
    docker compose version >/dev/null 2>&1 && echo "docker compose: $(docker compose version --short 2>&1)" || echo "docker compose: NOT FOUND (see AGENTS.md's Dev setup section)"
    docker buildx version >/dev/null 2>&1 && echo "docker buildx: $(docker buildx version 2>&1)" || echo "docker buildx: NOT FOUND (see AGENTS.md's Dev setup section)"
else
    echo "docker: not found"
fi
echo

# --- homelab role --------------------------------------------------------
if [[ -f "${REPO_ROOT}/deploy/homelab/docker-compose.yml" ]]; then
    echo "--- Homelab role ---"
    if [[ -f "$HOMELAB_ENV" ]]; then
        echo "deploy/homelab/.env: present"
        (
            set -a
            # shellcheck disable=SC1090
            source "$HOMELAB_ENV"
            set +a
            echo "  POSTGRES_PASSWORD: $(redact_status POSTGRES_PASSWORD)"
            echo "  ADMIN_USERNAME/PASSWORD: $(redact_status ADMIN_USERNAME)/$(redact_status ADMIN_PASSWORD)"
            echo "  SESSION_SECRET_KEY: $(redact_status SESSION_SECRET_KEY)"
            echo "  ROBOT_TOKENS: $(redact_status ROBOT_TOKENS)"
            echo "  SMTP_HOST (production email): $(redact_status SMTP_HOST)"
            echo "  REMOTE_UI_TOKEN: $(redact_status REMOTE_UI_TOKEN)"
        )
        if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
            if (cd "${REPO_ROOT}/deploy/homelab" && docker compose --env-file "$HOMELAB_ENV" config --quiet 2>/dev/null); then
                echo "  compose config: valid"
            else
                echo "  compose config: INVALID (run: cd deploy/homelab && docker compose config)"
            fi
        fi
    else
        echo "deploy/homelab/.env: not found (copy .env.example, see AGENTS.md's Dev setup section)"
    fi
    echo
fi

# --- embodiment-host role -------------------------------------------------
# Section runs whenever this host plausibly could be/is an embodiment
# host — real Reachy Mini devices present, a reachy-side env file exists,
# or the daemon unit is installed. Deliberately NOT gated on "daemon is
# already installed" alone: device/group/env checks are exactly the
# things worth knowing *before* installing the daemon (found live on the
# Nano — an earlier version of this script gated the whole section,
# including daemon-independent info, behind that one condition, so it
# silently vanished the moment daemon-install detection got fixed to be
# accurate on a host where it genuinely isn't installed yet).
DAEMON_ACTIVE=0
HAS_REACHY_DEVICES=0
[[ -e /dev/video0 || -e /dev/ttyACM0 || -d /dev/snd ]] && HAS_REACHY_DEVICES=1
DAEMON_INSTALLED=0
if command -v systemctl >/dev/null 2>&1 && systemd_unit_installed reachy-mini-daemon; then
    DAEMON_INSTALLED=1
fi

if [[ "$HAS_REACHY_DEVICES" -eq 1 || "$DAEMON_INSTALLED" -eq 1 || -f "$REACHY_ENV" ]]; then
    echo "--- Embodiment-host role ---"

    if [[ "$DAEMON_INSTALLED" -eq 1 ]]; then
        echo "reachy-mini-daemon.service: installed"
        if systemctl is-active --quiet reachy-mini-daemon; then
            DAEMON_ACTIVE=1
            echo "reachy-mini-daemon: active"
            # One curl call, not two — a second unguarded call here would
            # crash the whole script under set -e if the daemon became
            # unreachable between the two (the same class of bug just
            # fixed above: don't assume a command that just succeeded
            # will succeed again unguarded).
            STATUS_JSON="$(curl -fsS --max-time 5 http://127.0.0.1:8000/daemon/status 2>/dev/null || true)"
            if [[ -n "$STATUS_JSON" ]]; then
                echo "daemon /daemon/status: reachable"
                if command -v python3 >/dev/null 2>&1; then
                    printf '%s' "$STATUS_JSON" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(f"  state: {d.get(\"state\")}")
print(f"  simulation_enabled: {d.get(\"simulation_enabled\")}")
print(f"  mockup_sim_enabled: {d.get(\"mockup_sim_enabled\")}")
print(f"  hardware_id: {d.get(\"hardware_id\")}")
' 2>/dev/null || echo "  (could not parse status JSON)"
                fi
            else
                echo "daemon /daemon/status: NOT reachable"
            fi
        else
            echo "reachy-mini-daemon: not active"
        fi
    else
        echo "reachy-mini-daemon.service: NOT installed (see deploy/reachy/install-reachy-venv.sh and deploy/reachy/README.md)"
    fi

    # Always reported, regardless of daemon-install status — these are
    # exactly what you'd want to know before installing.
    echo "devices: video0=$([[ -e /dev/video0 ]] && echo present || echo missing), ttyACM0=$([[ -e /dev/ttyACM0 ]] && echo present || echo missing), snd=$([[ -d /dev/snd ]] && echo present || echo missing)"
    for grp in dialout video audio; do
        getent group "$grp" >/dev/null 2>&1 && echo "group '$grp': exists (gid $(getent group "$grp" | cut -d: -f3))" || echo "group '$grp': MISSING"
    done
    if [[ -f "$REACHY_ENV" ]]; then
        (
            set -a
            # shellcheck disable=SC1090
            source "$REACHY_ENV"
            set +a
            echo "deploy/reachy/.env: present (ROBOT_ID: $(redact_status ROBOT_ID), ROBOT_TOKEN: $(redact_status ROBOT_TOKEN), HUB_WS_URL: $(redact_status HUB_WS_URL))"
        )
    else
        echo "deploy/reachy/.env: not found (copy .env.example)"
    fi
    if docker ps --filter "name=^/reachy-embodiment\$" --filter status=running -q 2>/dev/null | grep -q .; then
        echo "reachy-embodiment container: running"
        curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null 2>&1 && echo "  /health: ok" || echo "  /health: NOT reachable"
    else
        echo "reachy-embodiment container: not running"
    fi
    echo
fi

# --- optional bounded hardware test --------------------------------------
if [[ "$TEST_HARDWARE" -eq 1 ]]; then
    echo "--- Hardware test (--test-hardware) ---"
    if [[ "$DAEMON_ACTIVE" -ne 1 ]]; then
        log_warn "reachy-mini-daemon is not active — skipping hardware test"
    else
        echo "This will move the robot's head/antennas briefly (a bounded 'wake_up' move)."
        if [[ "$ASSUME_YES" -ne 1 ]]; then
            read -r -p "Someone is physically present and watching the robot right now. Continue? [y/N] " reply
            [[ "$reply" =~ ^[Yy]$ ]] || { log_info "hardware test skipped (not confirmed)"; exit 0; }
        fi
        log_info "triggering a bounded wake_up move"
        if curl -fsS -X POST --max-time 10 http://127.0.0.1:8000/move/play/wake_up >/dev/null 2>&1; then
            log_info "wake_up move accepted by daemon — watch the robot to confirm real movement occurred"
        else
            log_error "wake_up move request failed"
        fi
    fi
    echo
fi

echo "=== end of report ==="
