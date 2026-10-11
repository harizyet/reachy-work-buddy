"""Explicit record references (daily-driver defect after Phase 44 closure): a named note or meeting is never taken for a task/reminder/alarm query, its stored text is
returned without a model, anything needing interpretation fails closed, and a reply that credits the owner's records without supplying one is withheld.

The regression is the real one: an empty task store, a real note titled "Tasks for next week", and a note body unlike the list the model once invented. All data is disposable."""

import functools
import json

import httpx
import pytest
from companion_core import record_reference
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.knowledge import routing
from companion_core.knowledge.selective_answer import (
    ZERO_EVIDENCE_REPLY,
    SelectiveAnswerer,
    access_for,
)
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.models import Meeting, MeetingJobStatus
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

from shared.models.response import Privacy

TITLE = "Tasks for next week"
BODY = "Renew the lab safety certificate\nOrder two replacement servo cables\nBook the dentist"
INVENTED = ("financial report", "marketing", "roadmap", "client email")
Q1 = "what tasks do I have?"
Q2 = "What did I write in the notes called 'my Tasks for next week'?"
Q3 = "According to my meeting notes called 'Tasks for next week', what do I need to do next week?"
HALLUCINATION = 'Based on your notes titled "Tasks for next week": 1. Prepare the financial report 2. Plan the marketing campaign 3. Update the product roadmap 4. Send the client email'


def build(model_reply: str = HALLUCINATION, *, notes=((TITLE, BODY, Privacy.WORK_PRIVATE),), meetings=()):
    calls = {"model": 0}

    def llm(request: httpx.Request) -> httpx.Response:
        calls["model"] += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": model_reply}}]})

    app = create_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False, llm_transport=httpx.MockTransport(llm),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    return app, calls, notes, meetings


class Session:
    def __init__(self, model_reply=HALLUCINATION, **kwargs):
        self.app, self.calls, notes, meetings = build(model_reply, **kwargs)
        self.notes, self.meetings = notes, meetings

    def __enter__(self):
        self.client = TestClient(self.app).__enter__()
        self.client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "reachy-local"}})
        for title, body, sensitivity in self.notes:
            self.client.portal.call(functools.partial(self.app.state.planner_store.add_note, title, body, sensitivity=sensitivity))
        for meeting in self.meetings:
            self.app.state.meeting_store._meetings[meeting.id] = meeting
        self.baseline = self.calls["model"]
        return self

    def __exit__(self, *exc):
        return self.client.__exit__(*exc)

    def say(self, text, modality="text", session="s"):
        body = {"session_id": session, "conversation_id": "c", "channel": "web", "text": text, "input_modality": modality}
        return self.client.post("/conversation", json=body).json()["reply"]

    @property
    def model_calls(self):
        return self.calls["model"] - self.baseline


# -- the real regression -------------------------------------------------------------------------------------------------------------

def test_what_tasks_do_i_have_still_uses_the_structured_store_and_no_model():
    with Session() as s:
        assert s.say(Q1) == "You have no open tasks."
        assert s.model_calls == 0
        s.client.portal.call(s.app.state.task_store.add_task, "water the plants")
        assert "water the plants" in s.say(Q1, session="t") and s.model_calls == 0


def test_a_title_that_says_my_tasks_returns_the_record_not_the_task_list():
    with Session() as s:
        reply = s.say(Q2)
        assert reply.startswith(f'Your note "{TITLE}"') and BODY in reply
        assert "no open tasks" not in reply.lower() and s.model_calls == 0


def test_a_grounded_question_about_the_record_fails_closed_and_the_model_is_not_called():
    with Session() as s:
        reply = s.say(Q3)
        assert reply == ZERO_EVIDENCE_REPLY == record_reference.COULD_NOT_ESTABLISH
        assert s.model_calls == 0 and not any(word in reply.lower() for word in INVENTED) and "Based on your notes" not in reply


@pytest.mark.parametrize("question", [Q2, Q3, "what did I write in the note called Tasks for next week?", "What did I write in the note called \"Tasks for next week\""])
def test_a_missing_record_is_said_to_be_missing_with_no_invented_content(question):
    with Session(notes=()) as s:
        reply = s.say(question)
        assert reply == record_reference.not_found_reply(record_reference.parse(question).title) and "couldn't find" in reply
        assert s.model_calls == 0 and not any(word in reply.lower() for word in INVENTED)


@pytest.mark.parametrize("title", ["my reminders", "Alarms for Friday", "my tasks", "Today's schedule", "What tasks are open", "Inbox clean-up list"])
def test_a_title_made_of_command_words_cannot_hijack_routing(title):
    with Session(notes=((title, "the stored words", Privacy.WORK_PRIVATE),)) as s:
        for question in (f"What did I write in the note called '{title}'?", f"show me the note titled {title}"):
            reply = s.say(question, session=question[:8])
            assert "the stored words" in reply and s.model_calls == 0


@pytest.mark.parametrize("text", ["list my reminders", "what reminders do I have?", "what alarms do I have?", "what's in my notes?", "what notes do I have?", "what tasks are open?"])
def test_ordinary_task_reminder_alarm_and_note_list_queries_are_not_record_references(text):
    assert record_reference.parse(text) is None


def test_ordinary_queries_keep_their_handlers():
    with Session() as s:
        assert s.say("what notes do I have?").startswith("Your notes:") and TITLE in s.say("what's in my notes?", session="u")
        assert "no upcoming reminders" in s.say("what reminders do I have?", session="v")
        assert s.say("add a task to buy milk", session="w") and "buy milk" in s.say(Q1, session="x")
        assert s.model_calls == 0


# -- access --------------------------------------------------------------------------------------------------------------------------

def test_a_record_the_channel_may_not_read_looks_exactly_like_a_missing_one():
    missing = record_reference.not_found_reply(TITLE)
    with Session(notes=((TITLE, BODY, Privacy.SENSITIVE),)) as s:
        assert s.say("what did I write in the note called Tasks for next week?") == missing and s.model_calls == 0
        assert s.say(Q3, session="q") == missing
    with Session() as s:  # work-private on the spoken channel: a shared speaker reads public records only
        assert s.say("what did I write in the note called Tasks for next week?", modality="voice") == missing
        assert BODY.splitlines()[0] in s.say("what did I write in the note called Tasks for next week?", session="t")


def test_two_records_with_the_same_readable_title_are_not_guessed_between():
    with Session(notes=((TITLE, "first", Privacy.WORK_PRIVATE), (TITLE.lower(), "second", Privacy.WORK_PRIVATE))) as s:
        assert s.say(Q2) == record_reference.ambiguous_reply("my Tasks for next week") and s.model_calls == 0


def meeting(title=TITLE, sensitivity=Privacy.WORK_PRIVATE, status=MeetingJobStatus.COMPLETE):
    return Meeting(title=title, source_filename="a.wav", content_type="audio/wav", audio_path="/dev/null", status=status, sensitivity=sensitivity,
                   transcript_segments=[{"start": 0, "end": 4, "text": "We agreed to rotate the on-call list."}])


def test_a_named_meeting_returns_its_transcript_and_an_unfinished_one_is_not_found():
    with Session(notes=(), meetings=(meeting(),)) as s:
        reply = s.say("what did I write in the meeting called Tasks for next week?")
        assert 'Your meeting "Tasks for next week"' in reply and "rotate the on-call list" in reply and s.model_calls == 0
        assert s.say(Q3, session="q") == ZERO_EVIDENCE_REPLY
    with Session(notes=(), meetings=(meeting(status=MeetingJobStatus.TRANSCRIBING),)) as s:
        assert s.say(Q2) == record_reference.not_found_reply("my Tasks for next week")


def test_a_long_record_is_cut_and_says_so():
    with Session(notes=((TITLE, "x" * 5000, Privacy.WORK_PRIVATE),)) as s:
        reply = s.say(Q2)
        assert "Showing the first 3000 of 5000 characters" in reply and reply.split("\n\n")[1].count("x") == 3000


# -- recognition ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("text", "title", "operation"), [
    (Q2, "my Tasks for next week", "retrieve"),
    (Q3, "Tasks for next week", "question"),
    ('what did I write in "Standup notes"', "Standup notes", "retrieve"),
    ("show me the note titled Weekly goals", "Weekly goals", "retrieve"),
    ("what's in the meeting called Kickoff?", "Kickoff", "retrieve"),
    ("what does the note named Packing list say?", "Packing list", "retrieve"),
    ("summarise the note called Weekly goals", "Weekly goals", "question"),
    ("what did I write about the budget in the note called Weekly goals?", "Weekly goals", "question"),
    ("According to my notes, what is due?", None, "question"),
    ("in my meeting notes, who owns the rollout?", None, "question"),
    ("what did I write in my notes?", None, "question"),
])
def test_explicit_references_are_recognised(text, title, operation):
    assert record_reference.parse(text) == record_reference.RecordReference(title, operation)


@pytest.mark.parametrize("text", [
    "delete the note called Tasks for next week", "add this to my notes", "remind me to read the note called Weekly goals", "write it in my notes",
    "rename the note called Weekly goals to Plan B", "/docs note called Weekly goals", "what is the capital of France?", "what did I write in my email to Dana?",
    "what tasks do I have?", "take a note called groceries",
])
def test_actions_commands_and_unrelated_text_are_not_references(text):
    assert record_reference.parse(text) is None


@pytest.mark.xfail(reason="needs the routing.py one-line guard, held back because routing.py is Phase 48 frozen (test_dev10_freeze); owner decision pending", strict=False)
def test_the_44e_classifier_no_longer_calls_a_named_record_a_status_question():
    assert routing.classify(Q1) == ("open_tasks", ())
    assert routing.classify(Q2) is None and routing.classify(Q3) is None
    assert routing.choose_path(Q2, attached_meeting=False) == "retrieval"
    assert routing.classify("what are my reminders?") is not None
    eligibility = SelectiveAnswerer(retriever=None, index_count=None)
    assert eligibility.classify(Q1, attached_meeting=False).reason == "status_question"
    assert eligibility.classify(Q3, attached_meeting=False).reason != "status_question"
    assert access_for("voice").sensitivity_ceiling == Privacy.PUBLIC


# -- the provenance backstop ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("reply", [
    HALLUCINATION, "According to your meeting notes you should call Dana.", "As per your notes, the review is Friday.", "Your notes say the vendor call moved.",
    "You wrote that the demo is on Monday.", "From your calendar, you are free at three.", "Per your meeting minutes, Priya owns it.",
])
def test_a_reply_crediting_the_owners_records_is_recognised(reply):
    assert record_reference.claims_unsupplied_provenance(reply)


@pytest.mark.parametrize("reply", [
    "I can't see your notes, so I can't say.", "I don't have access to your meeting notes.", "Paris is the capital of France.", "Based on your description, a Phillips head is best.",
    "Here is a short plan: stretch, then review the notes you bring.", "I couldn't establish that from the records I was able to check.",
])
def test_ordinary_replies_and_plain_denials_are_left_alone(reply):
    assert not record_reference.claims_unsupplied_provenance(reply)


def test_a_generated_answer_that_credits_records_the_turn_never_supplied_is_replaced():
    with Session() as s:
        reply = s.say("plan my week for me")  # no record named, no handler: the model answers and credits the owner's notes
        assert s.model_calls >= 1 and reply == ZERO_EVIDENCE_REPLY and "marketing" not in reply


def test_an_ordinary_generated_answer_is_untouched():
    with Session(HALLUCINATION.replace("Based on your notes titled", "A sensible plan")) as s:
        assert "A sensible plan" in s.say("plan my week for me")


def test_the_backstop_does_not_fire_when_a_meeting_was_attached_as_evidence():
    with Session("According to your meeting notes the rollout is Friday.", notes=(), meetings=(meeting("Rollout sync"),)) as s:
        meeting_id = next(iter(s.app.state.meeting_store._meetings))
        body = {"session_id": "m", "conversation_id": "c", "channel": "web", "text": "when is the rollout?", "input_modality": "text", "context_meeting_id": meeting_id}
        assert json.loads(json.dumps(s.client.post("/conversation", json=body).json()))["reply"].startswith("According to your meeting notes")
