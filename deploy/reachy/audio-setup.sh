#!/usr/bin/env bash
# Re-detects the Reachy Mini's USB audio card and regenerates ~/.asoundrc
# and mixer levels if either drifted since the daemon last started. USB
# audio enumeration order isn't stable across boots/replugs; a stale
# ~/.asoundrc card index silently breaks daemon audio (no animation sound
# effects, no mic capture) with no error visible anywhere else — found and
# fixed live during Phase 22b, see
# docs/verification/phase-22b-first-motion-2026-09-23.md.
#
# Shared by scripts/start-reachy.sh (manual launcher path) and
# reachy-mini-daemon.service's ExecStartPre (systemd boot path, added once
# the owner accepted unattended daemon boot start on a designated
# production Nano — see docs/deployment.md's "Robot host and Jetson Nano")
# so both paths use the same, once-validated logic instead of two copies
# drifting apart.
#
# Always exits 0: every step here is best-effort. Audio setup must never
# be the reason the daemon fails to start or ExecStartPre blocks it —
# motion working without audio is an acceptable degraded state; the
# reverse is not. Deliberately not `set -e` for the same reason: each
# check below is independent, not a pipeline that should abort partway.
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=../../scripts/lib/common.sh
if ! source "${SCRIPT_DIR}/../../scripts/lib/common.sh" 2>/dev/null; then
    # Minimal fallback if this ever runs from a layout where that relative
    # path doesn't resolve (e.g. ExecStartPre with an unexpected cwd) —
    # still must not be the reason audio setup, or the daemon start it
    # must never block, silently does nothing.
    log_info() { printf '[%s] INFO: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
    log_warn() { printf '[%s] WARN: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
fi

REACHY_VENV="${HOME}/reachy-venv"
ASOUNDRC="${HOME}/.asoundrc"
DETECTED_CARD=""

if [[ -x "${REACHY_VENV}/bin/python3" ]]; then
    # get_respeaker_card_number() returns 0 (not None) as its own "no card
    # found" default, and -1 on an arecord failure — a bare non-empty
    # check doesn't catch either, and would happily regenerate ~/.asoundrc
    # for HDMI (card 0) or a nonsense "hw:-1,0" if the robot's USB audio
    # isn't enumerated yet when this runs. Cross-check against
    # /proc/asound/cards before trusting the detected index at all.
    RAW_DETECTED_CARD="$("${REACHY_VENV}/bin/python3" -c 'from reachy_mini.media.audio_utils import get_respeaker_card_number; print(get_respeaker_card_number())' 2>/dev/null || true)"
    if [[ "$RAW_DETECTED_CARD" =~ ^[0-9]+$ ]] \
        && grep -qiE "^ *${RAW_DETECTED_CARD} \[.*\]: .*(Reachy Mini Audio|ReSpeaker)" /proc/asound/cards 2>/dev/null; then
        DETECTED_CARD="$RAW_DETECTED_CARD"
    else
        log_warn "reachy_mini.media.audio_utils did not report a real Reachy Mini/ReSpeaker card (got '${RAW_DETECTED_CARD}') — skipping ~/.asoundrc re-check and mixer reset this run"
    fi
else
    log_warn "reachy-venv not found at ${REACHY_VENV} — skipping audio device (~/.asoundrc) re-check"
fi

if [[ -n "$DETECTED_CARD" ]]; then
    if [[ -f "$ASOUNDRC" ]] && ! grep -q "hw:${DETECTED_CARD},0" "$ASOUNDRC" 2>/dev/null; then
        BACKUP="${ASOUNDRC}.stale-$(date +%Y%m%d%H%M%S)"
        if mv "$ASOUNDRC" "$BACKUP" 2>/dev/null; then
            log_warn "~/.asoundrc didn't reference detected audio card ${DETECTED_CARD} — backed up to $(basename "$BACKUP")"
        else
            log_warn "~/.asoundrc didn't reference detected audio card ${DETECTED_CARD}, but backing it up failed — leaving it in place, audio may not work"
        fi
    fi
    if [[ ! -f "$ASOUNDRC" ]]; then
        "${REACHY_VENV}/bin/python3" -c 'from reachy_mini.media.audio_utils import write_asoundrc_to_home; write_asoundrc_to_home()' \
            && log_info "regenerated ~/.asoundrc for detected audio card ${DETECTED_CARD}" \
            || log_warn "failed to regenerate ~/.asoundrc — audio may not work"
    fi
fi

# Best-effort restore of any persisted ALSA mixer levels. Try unprivileged
# first — the daemon's own user is normally in the `audio` group, which is
# usually sufficient for /dev/snd/controlC* access — then a non-interactive
# sudo as a fallback for a manual/interactive invocation; `-n` guarantees
# this never blocks on a password prompt that a boot-time ExecStartPre has
# no TTY to satisfy anyway.
alsactl restore >/dev/null 2>&1 || sudo -n alsactl restore >/dev/null 2>&1 \
    || log_warn "alsactl restore failed or found nothing saved — mixer levels may be at driver defaults"

if [[ -n "$DETECTED_CARD" ]]; then
    # alsactl restore keys saved state by the ALSA card *id* string (e.g.
    # "Audio"), not the numeric card index — found live: the same physical
    # card previously enumerated under a different id ("Audio_1") with an
    # old, quieter saved volume, which a plain restore would silently
    # reapply if the id ever drifts again. Set PCM volume explicitly by
    # the freshly detected numeric card instead of trusting restore alone.
    # Two distinct 'PCM' controls (,0 and ,1) were both found attenuated
    # live on this card — set both. Each call is independently
    # non-fatal.
    amixer -c "$DETECTED_CARD" sset 'PCM',0 100% unmute >/dev/null 2>&1 \
        || log_warn "could not set 'PCM',0 volume on card ${DETECTED_CARD} — audio may be quiet or muted"
    amixer -c "$DETECTED_CARD" sset 'PCM',1 100% unmute >/dev/null 2>&1 \
        || log_warn "could not set 'PCM',1 volume on card ${DETECTED_CARD} — audio may be quiet or muted"
fi

exit 0
