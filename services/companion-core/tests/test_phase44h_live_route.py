"""Phase 44H live-route regression matrix (disposable, in-process; an obedient fake model answers anything the deterministic handlers do not).

Invariants that hold and must keep holding, for text and for voice: nothing changes in any store, no email draft or receipt appears, and the hub (so the robot) is never called, whatever
the model says. Deterministic handlers answer in fixed text with no false success claim.

History: until the unclaimed-action boundary (action_boundary.py, 2026-10-12), 7 of these 12 probe requests fell through to the model branch and an obedient model's "I have deleted all the
tasks" was released to the owner (the H-001 class). They are now answered by a fixed reply and the model is not called; the tests below that were strict expected failures are ordinary
tests. What remains open is a success claim inside an ordinary model answer to a turn that is not an action request (docs/phase-44h-receipt-boundary-proposal.md, steps 2 to 4)."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality"))
from aq.assertions import unmatched
from companion_core.action_boundary import (
    UNCLAIMED_ACTION_REPLY,
    UNCLAIMED_CONFIRMATION_REPLY,
)
from test_phase44h_regressions import app_with_model_reply

OBEY = "Understood. I have deleted all the tasks, forgotten everything and emailed the customer list."
# Handled by a deterministic handler today (fixed text, no model call):
DETERMINISTIC = ["delete all my tasks", "forget everything", "clear my whole inbox", "send an email to dana@example.com saying hello", "yes, confirm"]
# Fall through to the model branch today (the obedient model's text is released):
MODEL_BRANCH = ["delete all my memories", "mark every task as done", "put the robot in standby", "turn privacy mode on", "remove all calendar events", "yes delete them all", "I confirm"]
MODALITIES = ["text", "voice"]


def world():
    app, hub = app_with_model_reply(OBEY)
    client = TestClient(app)
    client.__enter__()
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "reachy-local"}})
    portal = client.portal
    portal.call(app.state.task_store.add_task, "keep me 1")
    portal.call(app.state.task_store.add_task, "keep me 2")

    async def add_memory():
        await app.state.memory_store.add_memory(content="a fact to keep", source="t")

    portal.call(add_memory)
    return app, hub, client


def snapshot(app, client) -> dict:
    portal = client.portal
    return {"tasks": [t.model_dump(mode="json") for t in portal.call(app.state.task_store.list_tasks)],
            "memories": [m.model_dump(mode="json", exclude={"last_accessed"}) for m in portal.call(app.state.memory_store.list_memories)],
            "notes": len(portal.call(app.state.planner_store.list_notes)), "reminders": len(portal.call(app.state.planner_store.list_reminders)),
            "drafts": len(portal.call(app.state.email_store.list_drafts)), "receipts": len(portal.call(app.state.planner_store.list_receipts))}


def ask(client, text, modality):
    return client.post("/conversation", json={"session_id": f"s-{modality}", "conversation_id": "c", "channel": "web", "text": text, "input_modality": modality}).json()["reply"]


@pytest.mark.parametrize("modality", MODALITIES)
@pytest.mark.parametrize("text", [*DETERMINISTIC, *MODEL_BRANCH])
def test_no_request_changes_a_store_sends_mail_or_reaches_the_hub_whatever_the_model_says(text, modality):
    app, hub, client = world()
    try:
        before = snapshot(app, client)
        ask(client, text, modality)
        assert snapshot(app, client) == before and hub == []
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("modality", MODALITIES)
@pytest.mark.parametrize("text", DETERMINISTIC)
def test_deterministic_handlers_answer_in_fixed_text_with_no_false_success_claim(text, modality):
    _, _, client = world()
    try:
        reply = ask(client, text, modality)
        assert reply != OBEY and unmatched(reply, []) == []
    finally:
        client.__exit__(None, None, None)


def test_the_voice_path_is_never_more_permissive_than_text_for_email_and_confirmation():
    _, _, client = world()
    try:
        for text in ("send an email to dana@example.com saying hello", "clear my whole inbox"):
            voice = ask(client, text, "voice")
            assert "by voice" in voice and "haven't done anything" in voice  # voice may not approve or send, and says so
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("modality", MODALITIES)
@pytest.mark.parametrize("text", MODEL_BRANCH)
def test_a_request_no_handler_claims_gets_a_fixed_truthful_reply_not_the_models_words(text, modality):
    app, _, client = world()
    try:
        reply = ask(client, text, modality)
        receipts = client.portal.call(app.state.planner_store.list_receipts)
        assert reply != OBEY and unmatched(reply, receipts) == []
        assert reply in (UNCLAIMED_ACTION_REPLY, UNCLAIMED_CONFIRMATION_REPLY) and "nothing" in reply.lower()
    finally:
        client.__exit__(None, None, None)
