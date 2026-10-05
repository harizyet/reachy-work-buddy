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
