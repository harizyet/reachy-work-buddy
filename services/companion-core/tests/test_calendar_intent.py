from datetime import UTC, datetime, timedelta

from companion_core.calendar.models import CalendarEvent
from companion_core.calendar_intent import format_next_event_reply, is_next_event_query


def test_recognizes_common_phrasings() -> None:
    assert is_next_event_query("what's next")
    assert is_next_event_query("What's Next?")
    assert is_next_event_query("what do I have next")
    assert is_next_event_query("when's my next meeting")


def test_does_not_match_unrelated_text() -> None:
    assert not is_next_event_query("what's the weather like")
    assert not is_next_event_query("hello there")


def test_format_reply_with_no_events() -> None:
    assert format_next_event_reply(None) == "You have nothing else on your calendar."


def test_format_reply_with_an_event() -> None:
    event = CalendarEvent(
        title="Team Standup",
        start=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),  # a Monday
        end=datetime(2026, 1, 5, 10, 30, tzinfo=UTC),
        location="Room 4",
    )
    reply = format_next_event_reply(event)
    assert "Team Standup" in reply
    assert "Monday" in reply
    assert "10:00" in reply
    assert "Room 4" in reply


def test_format_reply_without_location() -> None:
    event = CalendarEvent(
        title="Solo focus time",
        start=datetime.now(UTC) + timedelta(hours=1),
        end=datetime.now(UTC) + timedelta(hours=2),
    )
    reply = format_next_event_reply(event)
    assert "Solo focus time" in reply
    assert " at " not in reply  # no location clause when location is unset
