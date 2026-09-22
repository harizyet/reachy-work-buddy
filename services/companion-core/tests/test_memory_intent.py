from companion_core.memory_intent import (
    format_capture_reply,
    format_confirmation_not_found_reply,
    format_forget_confirmation_reply,
    format_forget_not_found_reply,
    format_forgotten_reply,
    format_recall_reply,
    format_restore_not_found_reply,
    format_restored_reply,
    format_voice_confirmation_blocked_reply,
    match_capture,
    match_confirm_forget,
    match_forget,
    match_recall,
    match_restore,
    most_restrictive_privacy,
)

from shared.models.memory import MemoryRecord, MemoryType
from shared.models.response import Privacy


def _record(content: str, sensitivity: Privacy = Privacy.WORK_PRIVATE) -> MemoryRecord:
    return MemoryRecord(
        id="1", type=MemoryType.WORKING, content=content, source="conversation", sensitivity=sensitivity
    )


def test_match_capture_prefixes() -> None:
    assert match_capture("remember that my manager is Alice") == "my manager is Alice"
    assert match_capture("please remember that I like tea") == "I like tea"
    assert match_capture("remember to water the plants") == "to water the plants"


def test_match_capture_returns_none_for_unrelated_text() -> None:
    assert match_capture("what's next") is None
    assert match_capture("remember") is None  # nothing after the prefix


def test_match_recall_prefixes() -> None:
    assert match_recall("do you remember Alice") == "Alice"
    assert match_recall("what do you remember about my manager") == "my manager"
    assert match_recall("recall the project codename") == "the project codename"


def test_match_recall_returns_none_for_unrelated_text() -> None:
    assert match_recall("remember that I like tea") is None


def test_format_capture_reply() -> None:
    record = _record("my manager is Alice")
    assert format_capture_reply(record) == "I'll remember that: my manager is Alice."


def test_format_recall_reply_with_no_matches() -> None:
    assert format_recall_reply([], "Bob") == "I don't have anything stored about 'Bob'."


def test_format_recall_reply_with_matches() -> None:
    reply = format_recall_reply([_record("likes tea"), _record("works remotely")], "Alice")
    assert reply == "Here's what I remember: likes tea; works remotely."


def test_most_restrictive_privacy_picks_the_max() -> None:
    records = [
        _record("a", sensitivity=Privacy.PUBLIC),
        _record("b", sensitivity=Privacy.SENSITIVE),
        _record("c", sensitivity=Privacy.WORK_PRIVATE),
    ]
    assert most_restrictive_privacy(records) == Privacy.SENSITIVE


def test_most_restrictive_privacy_defaults_when_empty() -> None:
    assert most_restrictive_privacy([], default=Privacy.WORK_PRIVATE) == Privacy.WORK_PRIVATE


def test_match_forget_prefixes() -> None:
    assert match_forget("forget Alice") == "Alice"
    assert match_forget("forget that I like tea") == "I like tea"
    assert match_forget("delete memory about Alice") == "Alice"


def test_match_forget_returns_none_for_unrelated_text() -> None:
    assert match_forget("what's next") is None


def test_match_confirm_forget_prefixes() -> None:
    assert match_confirm_forget("yes forget Alice") == "Alice"
    assert match_confirm_forget("confirm forget Alice") == "Alice"


def test_match_confirm_forget_tolerates_stt_punctuation() -> None:
    """Discovered live-testing through the real voice pipeline:
    faster-whisper transcribed spoken "yes forget Alice" as "Yes, forget
    Alice." — comma right after "Yes" and a trailing period, both of which
    a literal prefix match rejected outright."""
    assert match_confirm_forget("Yes, forget Alice.") == "Alice"
    assert match_confirm_forget("Confirm forget Alice.") == "Alice"


def test_match_restore_prefixes() -> None:
    assert match_restore("restore Alice") == "Alice"
    assert match_restore("undo forget Alice") == "Alice"
    assert match_restore("unforget Alice") == "Alice"


def test_format_forget_confirmation_reply() -> None:
    record = _record("my manager is Alice")
    reply = format_forget_confirmation_reply(record, "Alice")
    assert "my manager is Alice" in reply
    assert "yes forget Alice" in reply


def test_format_forget_not_found_reply() -> None:
    assert "Alice" in format_forget_not_found_reply("Alice")


def test_format_forgotten_reply() -> None:
    record = _record("my manager is Alice")
    reply = format_forgotten_reply(record)
    assert "Forgotten" in reply
    assert "my manager is Alice" in reply
    assert "restore" in reply.lower()


def test_format_confirmation_not_found_reply() -> None:
    assert "Alice" in format_confirmation_not_found_reply("Alice")


def test_format_voice_confirmation_blocked_reply() -> None:
    reply = format_voice_confirmation_blocked_reply()
    assert "voice" in reply.lower()
    assert "text" in reply.lower()


def test_format_restore_not_found_reply() -> None:
    assert "Alice" in format_restore_not_found_reply("Alice")


def test_format_restored_reply() -> None:
    record = _record("my manager is Alice")
    reply = format_restored_reply(record)
    assert "Restored" in reply
    assert "my manager is Alice" in reply
