"""Open-palm stop, robot side (Phase 24e item 5, ADR 0023 addendum).

While the robot speaks a reply, it sends a few downscaled camera frames a
second to the hub, which checks them for a held open palm and answers
`stop` when it sees one. The hub turns this on per session
(`VoiceStartMessage.palm_stop`); the robot runs no detector itself. Frames
go only to the hub, only during playback, and are not stored anywhere.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

# About four frames a second: two consecutive hits at the hub are about
# half a second of a held palm.
DEFAULT_INTERVAL_SECONDS = 0.25


class PalmStopGone(Exception):
    """The hub no longer accepts frames for this reply (it ended, or palm
    stop is off); stop sending them."""


# (jpeg, voice_session_id, turn, generation) -> True when the hub says stop.
SendFrame = Callable[[bytes, str, int, int], Awaitable[bool]]


class HubPalmStop:
    """Captures and uploads frames during playback. `prepare` warms the
    camera at session start; `wait` returns once the hub says stop."""

    def __init__(
        self,
        capture_frame: Callable[[], bytes],
        send_frame: SendFrame,
        *,
        interval: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._capture_frame = capture_frame
        self._send_frame = send_frame
        self._interval = interval

    async def prepare(self) -> bool:
        """The first camera frames can take 7–12 s on the Nano, so this runs
        at session start, not when the first reply begins. A failure only
        delays the first frames."""
        try:
            await asyncio.to_thread(self._capture_frame)
        except Exception as exc:  # noqa: BLE001 - a late camera only delays detection
            log.info("palm stop camera warm-up failed, will retry during playback: %s", exc)
        log.info("palm stop ready")
        return True

    async def wait(self, voice_session_id: str, turn: int, generation: int) -> None:
        """Returns once the hub says stop. Camera or upload errors skip a
        frame; if the hub stops accepting frames this waits until the
        caller cancels it at the end of playback."""
        while True:
            try:
                frame = await asyncio.to_thread(self._capture_frame)
                if await self._send_frame(frame, voice_session_id, turn, generation):
                    return
            except PalmStopGone:
                await asyncio.Event().wait()
            except Exception as exc:  # noqa: BLE001 - one bad frame is not a reason to stop watching
                log.debug("palm stop frame skipped: %s", exc)
            await asyncio.sleep(self._interval)

    def close(self) -> None:
        pass
