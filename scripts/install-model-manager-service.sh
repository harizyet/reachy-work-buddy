#!/usr/bin/env bash
# Install the model manager as a systemd USER unit that starts with the machine (Phase 42, ADR 0031).
# It does not need root: the unit runs as you, with your Docker access. "Lingering" lets a user unit
# start at boot without a login; this script enables it for you (and tells you the one command to run
# yourself if the system refuses).
#
# Usage: scripts/install-model-manager-service.sh [--check] [--uninstall] [--help]
#   --check      Read-only: validates the unit file and prerequisites, writes and starts nothing.
#   --uninstall  Stop, disable and remove the unit (lingering is left as it is).
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
UNIT_SRC="${REPO_ROOT}/deploy/homelab/model-manager.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_DST="${UNIT_DIR}/model-manager.service"
UNINSTALL=0

print_help() {
    sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    print_common_help
}

parse_common_args "$@"
set -- "${COMMON_REMAINING_ARGS[@]+"${COMMON_REMAINING_ARGS[@]}"}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --uninstall) UNINSTALL=1 ;;
        --help) print_help; exit 0 ;;
        *) die "unknown argument: $1 (see --help)" ;;
    esac
    shift
done

require_cmd systemctl "systemd is required."
[[ "$(id -u)" -ne 0 ]] || die "run this as your own user, not root: it installs a user unit"
[[ "$REPO_ROOT" == "$HOME/reachy-work-buddy" ]] || die "the unit expects the repository at \$HOME/reachy-work-buddy (found $REPO_ROOT); edit WorkingDirectory/ExecStart in deploy/homelab/model-manager.service first"
[[ -f "$UNIT_SRC" ]] || die "missing $UNIT_SRC"
[[ -x "${REPO_ROOT}/scripts/start-model-manager.sh" ]] || die "scripts/start-model-manager.sh is not executable"

if [[ "$UNINSTALL" -eq 1 ]]; then
    systemctl --user disable --now model-manager.service 2>/dev/null || true
    rm -f "$UNIT_DST"
    systemctl --user daemon-reload
    log_info "removed the model-manager user unit"
    exit 0
fi

if [[ "$COMMON_CHECK_ONLY" -eq 1 ]]; then
    # The same minimal PATH the unit sets, so a missing tool shows here rather than at boot.
    env -i HOME="$HOME" PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" "${REPO_ROOT}/scripts/start-model-manager.sh" --check
    systemd-analyze --user verify "$UNIT_SRC" 2>&1 | grep -v "^$" || true
    log_info "linger: $(loginctl show-user "$USER" -p Linger 2>/dev/null || echo unknown)"
    log_info "installed: $([[ -f "$UNIT_DST" ]] && echo yes || echo no); active: $(systemctl --user is-active model-manager.service 2>/dev/null || true)"
    exit 0
fi

mkdir -p "$UNIT_DIR"
install -m 644 "$UNIT_SRC" "$UNIT_DST"
systemctl --user daemon-reload
systemctl --user enable --now model-manager.service
if ! loginctl enable-linger "$USER" 2>/dev/null; then
    log_warn "could not enable lingering; without it the manager only starts after you log in. Run once: sudo loginctl enable-linger $USER"
fi
sleep 3
log_info "model-manager: $(systemctl --user is-active model-manager.service); linger: $(loginctl show-user "$USER" -p Linger 2>/dev/null)"
