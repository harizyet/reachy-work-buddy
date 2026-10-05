"""Alarm delivery policy (ADR 0027): order, fallbacks and stop path."""

import asyncio

import httpx
import pytest
from reachy_hub import alarm_audio
from reachy_hub.alarm_delivery import (
    AlarmContext,
    AlarmDeliverer,
    Route,
    pre_occupancy_route,
)

ALARM = {"id": "a1", "label": "cake", "station_id": None}
OPEN = AlarmContext(privacy_mode=False, robot_available=True, occupied=False)


@pytest.mark.parametrize(
    ("ctx", "route"),
    [
        (AlarmContext(True, True, False), Route.TELEGRAM_PRIVACY),
        (AlarmContext(True, False, True), Route.TELEGRAM_PRIVACY),
        (AlarmContext(False, False, True), Route.TELEGRAM_UNAVAILABLE),
        (AlarmContext(False, True, True), Route.TELEGRAM_BUSY),
        (OPEN, Route.PLAY),
    ],
)
def test_route_order_is_privacy_then_availability_then_busy(ctx, route) -> None:
    assert pre_occupancy_route(ctx) is route


class Rig:
    def __init__(self, ctx=OPEN, present=True, push_ok=True, chunks=None, seconds=1.0) -> None:
        self.ctx, self.present, self.push_ok = ctx, present, push_ok
        self.chunks = chunks if chunks is not None else [alarm_audio.chime_wav(1.0)]
        self.checks = 0
        self.pushed: list[str] = []
        self.recorded: list[tuple[str, str]] = []
        self.played: list[bytes] = []
        self.stops = 0
        self.deliverer = AlarmDeliverer(
            context=self._context,
            check_present=self._present,
            push_telegram=self._push,
            record=self._record,
            play=self._play,
            stop_audio=self._stop,
            chunks_for=self._chunks,
            play_seconds=seconds,
        )

    async def _context(self):
        return self.ctx

    async def _present(self):
        self.checks += 1
        return self.present

    async def _push(self, text):
        self.pushed.append(text)
        return self.push_ok

    async def _record(self, alarm_id, outcome):
        self.recorded.append((alarm_id, outcome))

    async def _play(self, wav):
        self.played.append(wav)

    async def _stop(self):
        self.stops += 1

    async def _chunks(self, station_id, seconds):
        for chunk in self.chunks:
            yield chunk


@pytest.mark.parametrize(
    ("ctx", "reason"),
    [
        (AlarmContext(True, True, False), "privacy mode"),
        (AlarmContext(False, False, False), "robot unavailable"),
        (AlarmContext(False, True, True), "do not disturb"),
    ],
)
def test_blocked_alarms_go_to_telegram_without_a_sweep_or_audio(ctx, reason) -> None:
    rig = Rig(ctx=ctx)
    outcome = asyncio.run(rig.deliverer.deliver(ALARM))
    assert reason in outcome
    assert rig.pushed == ["Alarm: cake"]
    assert rig.checks == 0 and rig.played == []
    assert rig.recorded == [("a1", outcome)]


def test_empty_room_falls_back_to_telegram_marked_not_played() -> None:
    rig = Rig(present=False)
    outcome = asyncio.run(rig.deliverer.deliver(ALARM))
    assert outcome == "telegram: not played, nobody detected"
    assert rig.checks == 1 and rig.played == []
    assert "nobody detected" in rig.pushed[0]


def test_person_present_plays_and_records_without_telegram() -> None:
    rig = Rig()
    assert asyncio.run(rig.deliverer.deliver(ALARM)) == "played"
    assert len(rig.played) == 1 and rig.pushed == []
    assert rig.recorded == [("a1", "played")]
    assert not rig.deliverer.playing


def test_failed_telegram_send_is_recorded() -> None:
    rig = Rig(ctx=AlarmContext(True, True, False), push_ok=False)
    assert "send failed" in asyncio.run(rig.deliverer.deliver(ALARM))


def test_playback_error_silences_robot_and_falls_back_to_telegram() -> None:
    async def run():
        rig = Rig()

        async def broken(wav):
            raise httpx.ConnectError("down")

        rig.deliverer._play = broken
        outcome = await rig.deliverer.deliver(ALARM)
        return rig, outcome

    rig, outcome = asyncio.run(run())
    assert outcome.startswith("failed")
    assert rig.stops == 1 and rig.pushed == ["Alarm: cake (playback failed)"]


def test_stop_ends_playback_between_chunks_and_silences_robot() -> None:
    async def run():
        chime = alarm_audio.chime_wav(1.0)
        rig = Rig(chunks=[chime, chime, chime])
        first_played = asyncio.Event()
        original = rig.deliverer._play

        async def play(wav):
            await original(wav)
            first_played.set()

        rig.deliverer._play = play
        task = asyncio.create_task(rig.deliverer.deliver(ALARM))
        await first_played.wait()
        assert rig.deliverer.playing
        assert await rig.deliverer.stop() is True
        return rig, await task

    rig, outcome = asyncio.run(run())
    assert outcome == "stopped by owner" and len(rig.played) == 1 and rig.stops >= 1
    assert asyncio.run(rig.deliverer.stop()) is False


def test_second_alarm_while_one_plays_is_not_layered_on_top() -> None:
    async def run():
        rig = Rig()
        rig.deliverer._stop = asyncio.Event()
        return rig, await rig.deliverer.deliver(ALARM)

    rig, outcome = asyncio.run(run())
    assert outcome == Route.TELEGRAM_BUSY.value and rig.played == [] and rig.checks == 0
