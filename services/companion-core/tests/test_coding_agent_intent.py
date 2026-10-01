from companion_core.coding_agent_intent import (
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
    assert format_status_reply([]) == "You have no coding-agent sessions."


def test_format_status_reply_when_unreachable() -> None:
    assert format_status_reply(None) == "I can't reach the coding-agent service right now."


def test_format_status_reply_lists_sessions_with_readable_labels() -> None:
    reply = format_status_reply([_session(status="completed"), _session(status="running", id="s2")])
    assert "finished" in reply
    assert "running" in reply
    assert "Refactor module X" in reply


def test_format_usage_reply_only_covers_active_sessions() -> None:
    sessions = [_session(status="completed")]
    assert format_usage_reply(sessions, {}) == "You have no active coding-agent sessions."


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
