from datetime import UTC, datetime

import pytest
from companion_core.coding_agent_intent import (
    format_allowance_lines,
    format_completion_notification,
    format_status_reply,
    format_usage_reply,
    is_status_query,
    is_terminal,
    is_usage_query,
)


def test_recognizes_status_phrasings() -> None:
    assert is_status_query("is my coding session done")
    assert is_status_query("Did Claude finish?")
    assert is_status_query("check my claude session")
    assert not is_status_query("what's the weather like")


def test_recognizes_usage_phrasings() -> None:
    assert is_usage_query("what's my claude usage")
    assert is_usage_query("check my coding usage")
    assert not is_usage_query("is my coding session done")


def test_status_and_usage_are_distinct_intents() -> None:
    # A status question should not also fire the usage branch and vice
    # versa, since app.py's elif chain only runs one branch per turn.
    assert not is_usage_query("is my coding session done")
    assert not is_status_query("check my claude usage")


def _session(**overrides):
    base = {
        "id": "s1", "task_summary": "Refactor module X", "provider": "claude-code",
        "status": "running", "started_at": "2026-10-01T10:00:00Z", "owner_user_id": "owner-1",
    }
    base.update(overrides)
    return base


def test_format_status_reply_with_no_sessions() -> None:
    assert "no recorded coding-agent sessions managed by Reachy" in format_status_reply([])


def test_format_status_reply_when_unreachable() -> None:
    assert format_status_reply(None) == "I can't reach the coding-agent service right now."


def test_format_status_reply_lists_sessions_with_readable_labels() -> None:
    reply = format_status_reply([_session(status="completed"), _session(status="running", id="s2")])
    assert "finished" in reply
    assert "running" in reply
    assert "Refactor module X" in reply


def test_format_usage_reply_includes_finished_sessions() -> None:
    sessions = [_session(status="completed")]
    assert "Refactor module X" in format_usage_reply(sessions, {})


def test_format_usage_reply_reports_known_dimensions_only() -> None:
    sessions = [_session(status="running")]
    usage = {"s1": {"dimensions": [
        {"name": "input_tokens", "value": 1200.0, "unit": "tokens"},
        {"name": "session_cost", "value": 0.04, "unit": "usd"},
    ]}}
    reply = format_usage_reply(sessions, usage)
    assert "input tokens 1200tokens" in reply
    assert "session cost 0.04usd" in reply


def test_format_usage_reply_without_usage_data_says_so() -> None:
    sessions = [_session(status="running")]
    reply = format_usage_reply(sessions, {})
    assert "no usage information available yet" in reply


def test_format_completion_notification_states_what_happened() -> None:
    text = format_completion_notification(_session(status="failed"))
    assert "Refactor module X" in text
    assert "failed" in text


def test_is_terminal() -> None:
    assert is_terminal("completed")
    assert is_terminal("failed")
    assert is_terminal("lost")
    assert is_terminal("stopped")
    assert not is_terminal("running")
    assert not is_terminal("waiting_for_input")


@pytest.mark.parametrize("text", [
    "Hi are any of my Claude code sessions still running?",
    "Are my Claude Code sessions active?",
    "Is Claude Code still running?",
    "List my coding-agent sessions",
    "Has my Claude Code session completed?",
])
def test_natural_status_questions(text):
    assert is_status_query(text)
    assert not is_usage_query(text)


@pytest.mark.parametrize("text", [
    "What is my Claude code usage so far?",
    "What is the Claude code usage for my completed sessions?",
])
def test_usage_wins_over_session_status(text):
    assert is_usage_query(text)
    assert not is_status_query(text)


@pytest.mark.parametrize("text", ["Is my download running?", "What is Claude Code?", "Write code for a session manager"])
def test_unrelated_questions_are_not_session_queries(text):
    assert not is_status_query(text)


def test_empty_usage_is_not_a_claim_of_zero_account_usage():
    reply = format_usage_reply([], {})
    assert "no recorded coding-agent usage" in reply
    assert "not account-wide" in reply
    assert "restarts" not in reply
    assert "not a live reading" in reply


def _numbered_session(index: int, provider: str = "claude-code") -> dict:
    return {
        "id": f"s{index}", "task_summary": f"task {index}", "provider": provider,
        "status": "completed", "started_at": f"2026-10-01T10:{index:02d}:00+00:00",
    }


def test_status_and_usage_replies_show_the_five_newest_and_count_the_rest():
    sessions = [_numbered_session(i) for i in range(8)]
    status = format_status_reply(sessions)
    assert "task 7" in status and "task 3" in status
    assert "task 2" not in status
    assert "3 older sessions" in status
    usage = format_usage_reply(sessions, {})
    assert "task 3" in usage and "task 2" not in usage
    assert "3 older sessions" in usage


def test_allowance_lines_use_the_persona_timezone_and_skip_unknown_windows():
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    lines = format_allowance_lines([{"provider": "claude-code", "windows": [
        {"name": "five_hour_window", "value": 87.0, "unit": "%", "resets_at": "2026-10-01T15:40:00Z"},
        {"name": "weekly_window", "value": 41.5, "unit": "%", "resets_at": "2026-10-04T09:00:00Z"},
        {"name": "invented_window", "value": 5, "unit": "%", "resets_at": "2026-10-04T09:00:00Z"},
    ]}], now, "Asia/Kuala_Lumpur")
    assert lines == [
        "Claude 5-hour window: 87% used, resets today 11:40 PM",
        "Claude weekly window: 42% used, resets Sun 5:00 PM",
    ]


def test_usage_reply_without_allowance_says_it_is_unreported_not_zero():
    reply = format_usage_reply([_numbered_session(1)], {}, [])
    assert "has not reported your allowance" in reply
    assert "0%" not in reply


def test_usage_reply_hides_allowance_windows_from_per_session_lines():
    usage = {"s1": {"dimensions": [
        {"name": "input_tokens", "value": 12, "unit": "tokens"},
        {"name": "five_hour_window", "value": 87.0, "unit": "%"},
    ]}}
    reply = format_usage_reply([_numbered_session(1)], usage, ["Claude 5-hour window: 87% used, resets today 3:40 PM"])
    assert "input tokens 12tokens" in reply
    assert "five hour window" not in reply
    assert "Claude 5-hour window: 87% used" in reply


def test_usage_reply_with_live_allowance_and_no_sessions() -> None:

    lines = ["Claude 5-hour window: 42% used, resets today 3:00 PM"]
    reply = format_usage_reply([], {}, lines, allowance_live=True)
    assert lines[0] in reply
    assert "live reading" in reply
    assert "no recorded coding-agent sessions" in reply
