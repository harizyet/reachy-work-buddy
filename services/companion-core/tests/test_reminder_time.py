from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from companion_core.reminder_time import split_reminder_time

TZ = "Asia/Singapore"
ZONE = ZoneInfo(TZ)
NOW = datetime(2026, 10, 4, 6, 0, tzinfo=UTC)  # 14:00 in Singapore


@pytest.mark.parametrize(
    ("text", "task", "hour_utc", "day"),
    [
        ("send an email to brian later at 4pm", "send an email to brian", 8, 4),
        ("call mum at 9am", "call mum", 1, 5),  # already past today, so tomorrow
        ("submit report tomorrow at 10:30 am.", "submit report", 2, 5),
        ("stretch at 16:00", "stretch", 8, 4),
    ],
)
def test_at_times(text, task, hour_utc, day) -> None:
    got_task, due = split_reminder_time(text, NOW, TZ)
    assert got_task == task
    assert (due.astimezone(UTC).hour, due.astimezone(UTC).day) == (hour_utc, day)


def test_relative_and_tomorrow() -> None:
    task, due = split_reminder_time("check oven in 20 minutes", NOW, TZ)
    assert task == "check oven" and (due - NOW).total_seconds() == 1200
    task, due = split_reminder_time("pay rent tomorrow", NOW, TZ)
    assert task == "pay rent" and due.astimezone(ZONE).hour == 9


@pytest.mark.parametrize("text", ["buy milk", "meet at 4", "meet at 25pm", "meet at 13pm", "buy milk later"])
def test_no_clear_time_means_no_reminder(text) -> None:
    assert split_reminder_time(text, NOW, TZ) == (text, None)
