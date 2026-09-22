#!/usr/bin/env bash
# shellcheck disable=SC2034  # several globals here are consumed by whichever script sources this file, not by this file itself
#
# Shared helpers for scripts/start-*.sh and scripts/check-platform.sh.
# Sourced, not executed directly: `source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"`.
#
# Phase 22 (docs/phase-22-23.md's "Bash launcher contract"): every launcher
# resolves paths relative to itself, quotes arguments, runs under strict
# mode, uses bounded waits, and shares the --env-file/--no-browser/--check/
# --help flags. This file is where that shared behaviour actually lives,
# so the four scripts don't each reimplement it slightly differently.

set -Eeuo pipefail

# --- logging -----------------------------------------------------------
# Plain, timestamped, to stderr — stdout stays free for a script's actual
# machine-usable output (e.g. a printed URL) if it ever needs one.

_log() {
    local level="$1"
    shift
    printf '[%s] %s: %s\n' "$(date -u +%H:%M:%S)" "$level" "$*" >&2
}
log_info() { _log "INFO" "$*"; }
log_warn() { _log "WARN" "$*"; }
log_error() { _log "ERROR" "$*"; }

die() {
    log_error "$*"
    exit 1
}

# --- common flag parsing ------------------------------------------------
# Populates these globals; callers add their own script-specific flags in
# their own loop before/after calling this, or by extending CLI_ARGS.
# Never echoes secrets: flag *values* here are a path and booleans only.

COMMON_ENV_FILE=""
COMMON_NO_BROWSER=0
COMMON_CHECK_ONLY=0

# Sets COMMON_ENV_FILE/COMMON_NO_BROWSER/COMMON_CHECK_ONLY and populates
# the global COMMON_REMAINING_ARGS array with whatever it didn't recognize,
# so a caller's own loop can continue parsing script-specific flags.
#
# Must be called as a plain function call in the *same* shell — NOT via
# `< <(parse_common_args "$@")` process substitution, which runs the
# function in a subshell and silently discards every variable it sets
# once that subshell exits. (Caught by actually running start-homelab.sh
# --check live during Phase 22: --check didn't stop the stack from
# starting, because COMMON_CHECK_ONLY never made it back to the caller —
# this is exactly the AGENTS.md "verify by actually running it" lesson.)
#
# Usage: `parse_common_args "$@"; set -- "${COMMON_REMAINING_ARGS[@]}"`
# or iterate `COMMON_REMAINING_ARGS` directly.
COMMON_REMAINING_ARGS=()
parse_common_args() {
    COMMON_REMAINING_ARGS=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --env-file)
                [[ $# -ge 2 ]] || die "--env-file requires a path argument"
                COMMON_ENV_FILE="$2"
                shift 2
                ;;
            --env-file=*)
                COMMON_ENV_FILE="${1#--env-file=}"
                shift
                ;;
            --no-browser)
                COMMON_NO_BROWSER=1
                shift
                ;;
            --check)
                COMMON_CHECK_ONLY=1
                shift
                ;;
            *)
                COMMON_REMAINING_ARGS+=("$1")
                shift
                ;;
        esac
    done
}

# --- env file loading -----------------------------------------------------
# Never prints the file's contents — per phase-22-23.md: "Do not print
# secrets or full interpolated Compose configuration."

load_env_file() {
    local path="$1"
    [[ -f "$path" ]] || die "env file not found: $path"
    # SC1090: path is caller-supplied by design, shellcheck can't follow it.
    set -a
    # shellcheck disable=SC1090
    source "$path"
    set +a
    log_info "loaded environment from $path"
}

# Redacts a value for display: shows whether a variable is set, never its
# content. Used for diagnostic reports (check-platform.sh) — "Phase 22:
# Do not print secrets... a redacted diagnostic report."
redact_status() {
    local var_name="$1"
    if [[ -n "${!var_name:-}" ]]; then
        echo "set"
    else
        echo "unset"
    fi
}

# --- readiness waits ------------------------------------------------------
# Bounded, not indefinite — phase-22-23.md's acceptance matrix expects
# "GUI/core/hub ready within 120s", not an unbounded hang.

# wait_for_http URL TIMEOUT_SECONDS [INTERVAL_SECONDS]
wait_for_http() {
    local url="$1" timeout="$2" interval="${3:-2}"
    local waited=0
    log_info "waiting for $url (timeout ${timeout}s)"
    while (( waited < timeout )); do
        if curl -fsS -o /dev/null --max-time "$interval" "$url" 2>/dev/null; then
            log_info "$url is ready"
            return 0
        fi
        sleep "$interval"
        waited=$(( waited + interval ))
    done
    log_error "$url did not become ready within ${timeout}s"
    return 1
}

# --- browser opening -------------------------------------------------------
# "GUI startup means serving the web assets and opening their URL with the
# local desktop browser when available. Over SSH/headless boot, print the
# reachable URL; do not fail an otherwise healthy startup for lack of a
# display. Never auto-login or put credentials in URLs."

open_browser_or_print() {
    local url="$1"
    if [[ "$COMMON_NO_BROWSER" -eq 1 ]]; then
        log_info "GUI ready: $url"
        return 0
    fi
    if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
        log_info "no local display detected (SSH/headless) — GUI ready: $url"
        return 0
    fi
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 &
        disown 2>/dev/null || true
        log_info "opened $url in the default browser"
    elif command -v open >/dev/null 2>&1; then
        open "$url" >/dev/null 2>&1 &
        disown 2>/dev/null || true
        log_info "opened $url in the default browser"
    else
        log_info "no browser opener found — GUI ready: $url"
    fi
}

# --- misc -------------------------------------------------------------

require_cmd() {
    local cmd="$1" hint="${2:-}"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        if [[ -n "$hint" ]]; then
            die "required command '$cmd' not found. $hint"
        fi
        die "required command '$cmd' not found"
    fi
}

print_common_help() {
    cat <<'EOF'
Common flags (shared by every scripts/*.sh launcher):
  --env-file PATH   Load environment variables from PATH before starting.
  --no-browser      Never try to open a local browser; only print the URL.
  --check           Run readiness/diagnostic checks only; start nothing.
  --help            Show this script's help and exit.
EOF
}
