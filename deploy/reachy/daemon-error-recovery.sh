#!/usr/bin/env bash
# Restart reachy-mini-daemon once per boot if it reports `state: error`.
# Run by reachy-daemon-recovery.service, on the designated production Nano
# only (owner decision, 2026-09-25; see docs/deployment.md).
#
# The daemon does not exit when its start-up wake-up fails: it stays up
# with `state: error` and leaves the head wherever the failed goto stopped
# (24d: `time value is out of range [0,1]` at boot). systemd's
# Restart=on-failure never sees that, so this polls the status instead.
# Only `state` is used: in reachy_mini 1.8.4 `backend_status.ready` is
# always false.
#
# A restart replays the daemon's wake-up motion unattended, so it happens
# at most once per boot. The marker lives in /run, which is cleared at
# boot. A second error is logged at crit priority and the unit exits
# failed, leaving the daemon alone for the owner.
set -u

STATUS_URL="${REACHY_DAEMON_STATUS_URL:-http://127.0.0.1:8000/api/daemon/status}"
MARKER="${REACHY_RECOVERY_MARKER:-/run/reachy-daemon-recovery.restarted}"
INTERVAL="${REACHY_RECOVERY_INTERVAL:-5}"
DAEMON_SERVICE=reachy-mini-daemon

log() { logger -t reachy-daemon-recovery -p "user.$1" -- "$2"; echo "$2" >&2; }

daemon_state() {
    python3 - "$STATUS_URL" <<'EOF' 2>/dev/null
import json, sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=3) as resp:
    print(json.load(resp).get("state", ""))
EOF
}

while true; do
    # An unreachable daemon (starting, restarting, stopped for standby)
    # is not an error for this script: systemd owns process failures.
    if [[ "$(daemon_state)" == "error" ]]; then
        if [[ -e "$MARKER" ]]; then
            log crit "reachy-mini-daemon is in state error again after this boot's automatic restart; not restarting. Owner action needed (journalctl -u $DAEMON_SERVICE)."
            exit 1
        fi
        touch "$MARKER"
        log warning "reachy-mini-daemon reports state error; restarting it once for this boot (replays its wake-up motion)."
        systemctl restart "$DAEMON_SERVICE" \
            || log err "systemctl restart $DAEMON_SERVICE failed"
    fi
    sleep "$INTERVAL"
done
