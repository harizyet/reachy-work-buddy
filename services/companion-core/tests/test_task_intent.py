from companion_core.task_intent import (
    format_capture_reply,
    format_complete_reply,
    format_list_reply,
    format_search_reply,
    is_list_query,
    match_capture,
    match_complete,
    match_search,
)
from companion_core.tasks.models import Task


def test_match_capture_recognizes_common_phrasings() -> None:
    assert match_capture("remind me to buy milk") == "buy milk"
    assert match_capture("add task call the dentist") == "call the dentist"
    assert match_capture("todo: finish the report") == "finish the report"
    assert match_capture("note to self: bring charger") == "bring charger"


def test_match_capture_returns_none_for_unrelated_text() -> None:
    assert match_capture("what's the weather like") is None
    assert match_capture("hello there") is None


def test_match_capture_returns_none_for_empty_content() -> None:
    assert match_capture("remind me to ") is None
    assert match_capture("todo:") is None


def test_match_complete() -> None:
    assert match_complete("complete task buy milk") == "buy milk"
    assert match_complete("done with the report") == "the report"
    assert match_complete("hello there") is None


def test_match_search() -> None:
    assert match_search("search tasks for milk") == "milk"
    assert match_search("find task dentist") == "dentist"
    assert match_search("hello there") is None


def test_is_list_query() -> None:
    assert is_list_query("what are my tasks")
    assert is_list_query("show my tasks please")
    assert is_list_query("My To-Dos")
    assert not is_list_query("what's the weather like")


def test_format_replies() -> None:
    task = Task(text="buy milk")
    assert "buy milk" in format_capture_reply(task)

    assert format_list_reply([]) == "You have no open tasks."
    assert "buy milk" in format_list_reply([task])

    assert format_complete_reply(None, "milk") == "I couldn't find an open task matching 'milk'."
    assert "buy milk" in format_complete_reply(task, "milk")

    assert format_search_reply([], "milk") == "No tasks found matching 'milk'."
    assert "buy milk" in format_search_reply([task], "milk")


def test_natural_task_and_reminder_questions_are_list_queries() -> None:
    from companion_core.task_intent import is_reminder_list_query

    assert is_list_query("Do I currently have any tasks I need done?")
    assert is_list_query("what to-dos do I have")
    assert not is_list_query("tell me a joke")
    assert is_reminder_list_query("Do I have any reminders?")
    assert is_reminder_list_query("what reminders do I have today")
    assert not is_reminder_list_query("set a reminder for 4pm")
    assert not is_reminder_list_query("remind me to call mum")


def test_note_list_questions() -> None:
    from companion_core.task_intent import is_note_list_query

    assert is_note_list_query("Do I have any notes?")
    assert is_note_list_query("show my notes")
    assert not is_note_list_query("take a note about the meeting")
    assert not is_note_list_query("what's the weather")


def test_contractions_punctuation_and_singular_task_are_list_queries() -> None:
    from companion_core.task_intent import BARE_TASK_LIST, normalise_question

    for text in ["whats my task for next week?", "what's my task for next week?", "What’s my task", "what is my task", "WHATS MY TASKS", "tasks for next week", "my to-dos today"]:
        assert is_list_query(text), text
    assert normalise_question("Whats my task") == "what is my task"
    assert normalise_question("what’re my tasks").lower() == "what are my tasks"
    assert normalise_question("whatsapp me") == "whatsapp me"
    assert BARE_TASK_LIST.match("tasks for next week") and not BARE_TASK_LIST.match("tasks: buy milk")
    assert not is_list_query("whats the weather") and not is_list_query("whats up")


def test_time_scope_accepts_one_supported_window_and_flags_everything_else() -> None:
    from companion_core.task_intent import time_scope

    assert time_scope("next week").window == "next_week"
    assert time_scope("what's on this weekend").problem == "unsupported"  # "this week" is not a prefix match for "weekend"
    assert time_scope("the rest of this week").window == "this_week"
    assert time_scope("tonight").window == "today"
    assert time_scope("tomorrow and today").problem == "ambiguous"
    assert time_scope("next week on friday").problem == "unsupported"
    assert time_scope("hello").window is None and time_scope("hello").problem is None


def test_scoped_list_reply_is_honest_that_tasks_have_no_dates() -> None:
    from companion_core.task_intent import TimeScope

    task = Task(text="buy milk")
    reply = format_list_reply([task], TimeScope("next_week"))
    assert "buy milk" in reply and "don't carry due dates" in reply and "all undated" in reply
    assert format_list_reply([task], TimeScope(None, "unsupported")).startswith("I can only filter by")
    assert "buy milk" not in format_list_reply([task], TimeScope(None, "ambiguous"))
    assert format_list_reply([task]) == "Your open tasks: buy milk."
    assert format_list_reply([], TimeScope("today")) == "You have no open tasks."
