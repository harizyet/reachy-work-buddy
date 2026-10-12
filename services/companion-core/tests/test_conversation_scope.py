"""Short-term history is scoped per saved chat and attached context (hub-supplied), not shared by every web chat of the owner.

A privacy defect found at the Phase 50 chat-picker deployment: all of an owner's web chats shared one history, so a document's answers surfaced in
an unrelated chat. The hub now sends a server-derived `history_scope`; voice, Telegram and unscoped turns keep the per-session history.
"""

import json

import httpx
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.conversation import MAX_SCOPED_HISTORIES, ConversationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

from shared.models.response import Privacy

WEB = {"session_id": "s1", "conversation_id": "c1", "channel": "web", "input_modality": "text"}


def make_client(seen: list[list[str]]) -> TestClient:
    def respond(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        seen.append([m["content"] for m in json.loads(body)["messages"] if m["role"] != "system"])
        return httpx.Response(200, json={"choices": [{"message": {"content": f"reply {len(seen)}"}}]})

    client = TestClient(create_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(),
        meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False, llm_transport=httpx.MockTransport(respond),
    ))
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}})
    return client


def say(client: TestClient, text: str, **extra) -> dict:
    resp = client.post("/conversation", json={**WEB, "text": text, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_two_scopes_of_one_session_do_not_see_each_other() -> None:
    seen: list[list[str]] = []
    client = make_client(seen)
    say(client, "The harbour contract renews in March.", history_scope="chat:A:doc:d1")
    say(client, "What did we just talk about?", history_scope="chat:B")
    assert seen[1] == ["What did we just talk about?"]
    say(client, "And before that?", history_scope="chat:A:doc:d1")
    assert seen[2] == ["The harbour contract renews in March.", "reply 1", "And before that?"]  # continuity inside the same chat


def test_context_change_inside_one_chat_starts_a_clean_history() -> None:
    seen: list[list[str]] = []
    client = make_client(seen)
    say(client, "First document fact.", history_scope="chat:A:doc:d1")
    say(client, "Second document question.", history_scope="chat:A:doc:d2")
    say(client, "Plain question.", history_scope="chat:A")
    assert seen[1] == ["Second document question."]
    assert seen[2] == ["Plain question."]


def test_unscoped_turns_keep_the_shared_session_history_and_never_see_scoped_ones() -> None:
    seen: list[list[str]] = []
    client = make_client(seen)
    say(client, "Spoken before.", channel="reachy", input_modality="voice")
    say(client, "Typed in a chat.", history_scope="chat:A")
    say(client, "Spoken after.", channel="reachy", input_modality="voice")
    assert seen[1] == ["Typed in a chat."]
    assert seen[2] == ["Spoken before.", "reply 1", "Spoken after."]  # voice/Telegram continuity unchanged, and without the chat's turn


def test_prior_turns_restore_an_empty_scope_but_never_override_a_live_one() -> None:
    seen: list[list[str]] = []
    client = make_client(seen)
    prior = [{"text": "Earlier question.", "reply": "Earlier answer."}]
    say(client, "Follow-up.", history_scope="chat:A", prior_turns=prior)
    assert seen[0] == ["Earlier question.", "Earlier answer.", "Follow-up."]
    say(client, "Again.", history_scope="chat:A", prior_turns=[{"text": "Forged.", "reply": "Forged."}])
    assert "Forged." not in seen[1] and seen[1][-1] == "Again."
    say(client, "Unscoped.", prior_turns=prior)  # no scope: prior turns are ignored
    assert seen[2] == ["Unscoped."]


def test_forget_drops_a_chat_and_each_of_its_contexts_only() -> None:
    seen: list[list[str]] = []
    client = make_client(seen)
    say(client, "In A plain.", history_scope="chat:A")
    say(client, "In A with a document.", history_scope="chat:A:doc:d1")
    say(client, "In AB.", history_scope="chat:AB")
    r = client.post("/conversation/forget", json={"session_id": "s1", "history_scope": "chat:A"})
    assert r.json() == {"removed": 2}
    say(client, "Next in A.", history_scope="chat:A")
    say(client, "Next in AB.", history_scope="chat:AB")
    assert seen[3] == ["Next in A."]
    assert seen[4] == ["In AB.", "reply 3", "Next in AB."]  # a chat id that merely starts the same is untouched


def test_scoped_histories_are_bounded_and_the_oldest_leave_first() -> None:
    store = ConversationStore()
    for n in range(MAX_SCOPED_HISTORIES + 5):
        store.append(f"s\x1fchat:{n}", "web", "hi")
    store.append("plain-session", "reachy", "hi")
    assert store.messages("s\x1fchat:0") == []
    assert store.messages(f"s\x1fchat:{MAX_SCOPED_HISTORIES + 4}")
    assert store.messages("plain-session")  # unscoped sessions are never evicted


def test_seeded_replies_carry_a_work_private_label() -> None:
    store = ConversationStore()
    assert store.seed_if_empty("s\x1fchat:A", [("q", "a")])
    assert store.reply_privacy("s\x1fchat:A", Privacy.PUBLIC) == Privacy.WORK_PRIVATE
    assert not store.seed_if_empty("s\x1fchat:A", [("x", "y")])
