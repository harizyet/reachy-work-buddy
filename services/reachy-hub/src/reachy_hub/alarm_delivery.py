"""Phase 38.4 (ADR 0027): how a due alarm is delivered.

The order is fixed and checked cheapest-first, so the sweep (robot motion)
only runs once every earlier rule has allowed audio: privacy mode, robot
availability, do-not-disturb/meeting, then occupancy. Anything but a
confirmed presence falls back to Telegram with the reason, never to silence.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx

from reachy_hub import alarm_audio

log = logging.getLogger(__name__)


class Route(StrEnum):
    PLAY = "play"
    TELEGRAM_PRIVACY = "telegram: privacy mode"
    TELEGRAM_UNAVAILABLE = "telegram: robot unavailable"
    TELEGRAM_BUSY = "telegram: do not disturb or meeting"
    TELEGRAM_ABSENT = "telegram: not played, nobody detected"


@dataclass(frozen=True)
class AlarmContext:
    privacy_mode: bool
    robot_available: bool
    occupied: bool


def pre_occupancy_route(ctx: AlarmContext) -> Route:
    if ctx.privacy_mode:
        return Route.TELEGRAM_PRIVACY
    if not ctx.robot_available:
        return Route.TELEGRAM_UNAVAILABLE
    if ctx.occupied:
        return Route.TELEGRAM_BUSY
    return Route.PLAY


class AlarmDeliverer:
    def __init__(
        self,
        *,
        context: Callable[[], Awaitable[AlarmContext]],
        check_present: Callable[[], Awaitable[bool]],
        push_telegram: Callable[[str], Awaitable[bool]],
        record: Callable[[str, str], Awaitable[Any]],
        play: Callable[[bytes], Awaitable[Any]],
        stop_audio: Callable[[], Awaitable[Any]],
        chunks_for: Callable[[str | None, float], AsyncIterator[bytes]],
        play_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._context = context
        self._check_present = check_present
        self._push = push_telegram
        self._record = record
        self._play = play
        self._stop_audio = stop_audio
        self._chunks_for = chunks_for
        self._play_seconds = play_seconds
        self._clock = clock
        self._stop: asyncio.Event | None = None

    @property
    def playing(self) -> bool:
        return self._stop is not None

    async def stop(self) -> bool:
        """Ends a playing alarm and silences the robot. False when idle."""
        if self._stop is None:
            return False
        self._stop.set()
        with contextlib.suppress(httpx.HTTPError):
            await self._stop_audio()
        return True

    async def deliver(self, alarm: dict[str, Any]) -> str:
        label = alarm["label"]
        route = pre_occupancy_route(await self._context())
        if route is Route.PLAY and self.playing:
            route = Route.TELEGRAM_BUSY
        if route is Route.PLAY and not await self._check_present():
            route = Route.TELEGRAM_ABSENT

        if route is not Route.PLAY:
            suffix = " (not played: nobody detected in the room)" if route is Route.TELEGRAM_ABSENT else ""
            sent = await self._push(f"Alarm: {label}{suffix}")
            outcome = route.value if sent else f"{route.value} (telegram send failed)"
            await self._record(alarm["id"], outcome)
            return outcome

        outcome = await self._play_alarm(alarm)
        await self._record(alarm["id"], outcome)
        if outcome.startswith("failed"):
            await self._push(f"Alarm: {label} (playback failed)")
        return outcome

    async def _play_alarm(self, alarm: dict[str, Any]) -> str:
        stop = asyncio.Event()
        self._stop = stop
        try:
            kwargs = {"clock": self._clock} if self._clock else {}
            played = await alarm_audio.play_chunks(
                self._play, self._chunks_for(alarm.get("station_id"), self._play_seconds), stop, **kwargs
            )
        except (httpx.HTTPError, alarm_audio.StreamError, RuntimeError, ValueError, OSError) as exc:
            log.warning("alarm playback failed: %s", exc)
            with contextlib.suppress(httpx.HTTPError):
                await self._stop_audio()
            return "failed: playback error"
        finally:
            self._stop = None
        if stop.is_set():
            return "stopped by owner"
        return "played" if played else "failed: no audio"
