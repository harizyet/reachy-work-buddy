#!/usr/bin/env bash
# Wait until reachy-mini-daemon has created its camera socket, before the
# reachy-embodiment container starts. Shared by scripts/start-reachy.sh and
# reachy-embodiment.service so both paths apply the same precondition.
#
# Starting the container first is what broke Nano reboots: Docker's
# `unless-stopped` policy brought it up before the daemon, the old `-v`
# bind created /tmp/reachymini_camera_socket as a root-owned directory, and
# the daemon could no longer create its socket (EPERM). This script never
# deletes that directory: the daemon has already failed its media setup by
# then, and recovering needs a daemon restart, which moves the robot and
# needs the owner present.
#
# Usage: wait-media-socket.sh [timeout-seconds]   (default 120)
# Exit: 0 socket ready, 1 timed out, 2 a directory is blocking the path.
set -u

SOCKET="${REACHY_CAMERA_SOCKET:-/tmp/reachymini_camera_socket}"
TIMEOUT="${1:-120}"

for ((i = 0; i <= TIMEOUT; i++)); do
    if [[ -S "$SOCKET" ]]; then
        exit 0
    fi
    if [[ -d "$SOCKET" ]]; then
        echo "$SOCKET is a directory, left by an old container bind. With the owner present: sudo rm -rf $SOCKET, then sudo systemctl restart reachy-mini-daemon (this runs its wake-up motion)." >&2
        exit 2
    fi
    ((i < TIMEOUT)) && sleep 1
done
echo "timed out after ${TIMEOUT}s waiting for reachy-mini-daemon to create $SOCKET (check: journalctl -u reachy-mini-daemon)" >&2
exit 1
