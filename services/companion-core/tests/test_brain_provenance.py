"""Phase 47 Brain x Phase 49 provenance: `derived_from` edges from an accepted task or reminder to the Notepad note it was created from.

The edge comes from the stored provenance row only (no text, similarity, time or model). Both ends must be requested, exist, and pass the node visibility check; the
edge id is the proposal id; the summary counts exactly what the edge endpoint returns; and the edges stay readable when NOTEPAD_PROCESSING_ENABLED is off (the flag governs
new processing, not historical provenance)."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.notepad_processing.models import (
    Job,
    Kind,
    Proposal,
    ProposalStatus,
    Provenance,
    content_hash,
    fingerprint,
)
from companion_core.notepad_processing.service import NotepadService
from companion_core.notepad_processing.store import InMemoryNotepadStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

from shared.models.response import Privacy

NOW = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)


class World:
    def __init__(self, monkeypatch, *, flag: bool = False) -> None:
        (monkeypatch.setenv("NOTEPAD_PROCESSING_ENABLED", "true") if flag else monkeypatch.delenv("NOTEPAD_PROCESSING_ENABLED", raising=False))
        self.planner, self.tasks, self.notepad = InMemoryPlannerStore(), InMemoryTaskStore(), InMemoryNotepadStore()
        self.client = TestClient(create_app(
            calendar_store=InMemoryCalendarStore(), task_store=self.tasks, planner_store=self.planner, meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
            memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(embed_fn=lambda texts: [[0.0] * 384 for _ in texts]), email_store=InMemoryEmailStore(),
            confirmation_store=InMemoryConfirmationStore(), llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(),
            search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False, notepad_store=self.notepad, run_notepad_runner=False))

    def run(self, coro):
        return asyncio.run(coro)

    def note(self, title, body="text", sensitivity=Privacy.WORK_PRIVATE):
        return self.run(self.planner.add_note(title, body, sensitivity=sensitivity)).id

    def task(self, text, sensitivity=Privacy.WORK_PRIVATE):
        return self.run(self.tasks.add_task(text, sensitivity=sensitivity)).id

    def reminder(self, text, sensitivity=Privacy.WORK_PRIVATE):
        return self.run(self.planner.add_reminder(text, NOW + timedelta(days=30), sensitivity=sensitivity)).id

    def derive(self, kind, record_id, note_id, proposal_id=None, snapshot="0123456789abcdef"):
        row = Provenance(record_kind=kind, record_id=record_id, note_id=note_id, proposal_id=proposal_id or f"prop-{record_id[:8]}", snapshot_hash=snapshot)
        self.run(self.notepad.add_provenance(row))
        return f"derived_from:{row.proposal_id}"

    def edges(self, *node_ids):
        r = self.client.get("/brain/edges", params={"ids": ",".join(node_ids)})
        assert r.status_code == 200
        return r.json()

    def summary(self):
        return self.client.get("/brain/summary").json()

    def all_ids(self):
        out, cursor = [], None
        while True:
            body = self.client.get("/brain/nodes", params={"limit": 200, **({"cursor": cursor} if cursor else {})}).json()
            out += [n["id"] for n in body["nodes"]]
            cursor = body.get("next")
            if not cursor:
                return out


@pytest.fixture(params=[False, True], ids=["flag-off", "flag-on"])
def w(request, monkeypatch):
    return World(monkeypatch, flag=request.param)


def test_an_accepted_task_is_linked_to_its_visible_note(w):
    note, task = w.note("My Task for next week", "secret words here"), w.task("refactor clickhouse migration")
    edge_id = w.derive("task", task, note, "c910a964-e318-4a13-b201-5287627bec2f")
    body = w.edges(f"task:{task}", f"note:{note}")
    (edge,) = body["edges"]
    assert edge["id"] == edge_id == "derived_from:c910a964-e318-4a13-b201-5287627bec2f"
    assert (edge["from"], edge["to"], edge["kind"]) == (f"task:{task}", f"note:{note}", "derived_from")
    assert "secret words" not in json.dumps(body) and "My Task" not in json.dumps(body)  # the basis is about the relationship, never the note's text
    assert "01234567" in edge["basis"]  # it names the processed version


def test_an_accepted_reminder_is_linked_to_its_note(w):
    note, reminder = w.note("Calls"), w.reminder("phone the bank")
    w.derive("reminder", reminder, note)
    (edge,) = w.edges(f"reminder:{reminder}", f"note:{note}")["edges"]
    assert (edge["from"], edge["to"]) == (f"reminder:{reminder}", f"note:{note}")


def test_several_tasks_from_one_note_give_one_distinct_edge_each(w):
    note = w.note("Plan")
    tasks = [w.task(f"task {i}") for i in range(3)]
    ids = {w.derive("task", t, note) for t in tasks}
    body = w.edges(f"note:{note}", *[f"task:{t}" for t in tasks])
    assert {e["id"] for e in body["edges"]} == ids and len(body["edges"]) == 3
    assert {e["to"] for e in body["edges"]} == {f"note:{note}"}


def test_the_real_topology_each_task_belongs_to_its_own_note_only(w):
    notes = {"next_week": w.note("My Task for next week"), "git": w.note("GIT"), "project": w.note("Reachy Project")}
    clickhouse, gitlab = w.task("refactor clickhouse migration"), w.task("spin up gitlab repo")
    w.derive("task", clickhouse, notes["next_week"], "p-clickhouse")
    w.derive("task", gitlab, notes["git"], "p-gitlab")
    body = w.edges(*[f"note:{n}" for n in notes.values()], f"task:{clickhouse}", f"task:{gitlab}")
    pairs = {(e["from"], e["to"]) for e in body["edges"]}
    assert pairs == {(f"task:{clickhouse}", f"note:{notes['next_week']}"), (f"task:{gitlab}", f"note:{notes['git']}")}  # exactly these two; no cross links, none to "Reachy Project"


def test_a_restricted_note_or_task_yields_no_edge_and_no_trace(w):
    secret_note, plain_note = w.note("Therapy", sensitivity=Privacy.SENSITIVE), w.note("Plain")
    plain_task, secret_task = w.task("ok"), w.task("hidden task", sensitivity=Privacy.SENSITIVE)
    w.derive("task", plain_task, secret_note, "p-secret-note")
    w.derive("task", secret_task, plain_note, "p-secret-task")
    ids = [f"note:{secret_note}", f"note:{plain_note}", f"task:{plain_task}", f"task:{secret_task}"]
    body = w.edges(*ids)
    assert body["edges"] == []
    blob = json.dumps(body) + json.dumps(w.summary())
    assert "p-secret" not in blob and secret_note not in blob and secret_task not in blob
    assert body == w.edges(f"note:{plain_note}", f"task:{plain_task}", "task:does-not-exist", "note:does-not-exist")  # a restricted end looks like a missing one
    assert w.summary()["edges"] == 0


def test_a_deleted_note_or_task_leaves_no_visible_edge_but_the_provenance_row_stays(w):
    note_a, note_b = w.note("A"), w.note("B")
    task_a, task_b = w.task("from a"), w.task("from b")
    w.derive("task", task_a, note_a, "p-a")
    w.derive("task", task_b, note_b, "p-b")
    assert len(w.edges(f"note:{note_a}", f"note:{note_b}", f"task:{task_a}", f"task:{task_b}")["edges"]) == 2
    w.run(w.planner.delete_note(note_a))
    w.run(w.tasks.delete_task(task_b))
    assert w.edges(f"note:{note_a}", f"note:{note_b}", f"task:{task_a}", f"task:{task_b}")["edges"] == []
    assert w.run(w.notepad.get_provenance("task", task_a)) is not None and w.run(w.notepad.get_provenance("task", task_b)) is not None  # history is kept
    assert w.summary()["edges"] == 0


def test_editing_the_note_keeps_the_same_edge_to_the_historical_snapshot(w):
    note, task = w.note("Draft", "first version"), w.task("do it")
    w.derive("task", task, note, "p-edit", snapshot=content_hash("first version"))
    before = w.edges(f"note:{note}", f"task:{task}")
    w.run(w.planner.update_note(note, "Draft (renamed)", "a completely different second version"))
    after = w.edges(f"note:{note}", f"task:{task}")
    assert before == after and before["edges"][0]["id"] == "derived_from:p-edit" and content_hash("first version")[:8] in after["edges"][0]["basis"]


def test_a_pending_proposal_is_not_an_authoritative_record_and_gets_no_edge_or_node(w):
    note = w.note("Notes")
    quote = "Call the bank."
    pending = Proposal(job_id="j", note_id=note, snapshot_hash="h", kind=Kind.TASK, text="Call the bank", evidence=quote, span_start=0, span_end=len(quote), fingerprint=fingerprint(quote),
                       sensitivity=Privacy.WORK_PRIVATE, status=ProposalStatus.PENDING)
    job = Job(note_id=note, note_title="Notes", snapshot_text=quote, snapshot_hash="h", note_updated_at=NOW, timezone="UTC", sensitivity=Privacy.WORK_PRIVATE, inputs_hash="x")
    w.run(w.notepad.enqueue(job, force=False))
    pending = pending.model_copy(update={"job_id": job.id})
    w.run(w.notepad.claim_next(NOW))
    w.run(w.notepad.complete_job(job.id, [pending], model="m", now=NOW))
    assert len(w.run(w.notepad.list_proposals())) == 1
    assert w.edges(f"note:{note}")["edges"] == [] and w.summary()["edges"] == 0
    types = {i.split(":")[0] for i in w.all_ids()}
    assert types <= {"memory", "document", "meeting", "note", "task", "reminder"} and "proposal" not in types  # the Brain's scope is unchanged


def test_both_ends_must_be_in_the_requested_scope(w):
    note, task = w.note("N"), w.task("T")
    w.derive("task", task, note)
    assert w.edges(f"task:{task}")["edges"] == [] and w.edges(f"note:{note}")["edges"] == []
    assert len(w.edges(f"task:{task}", f"note:{note}")["edges"]) == 1


def test_summary_and_edges_agree_and_repeated_requests_give_no_duplicates(w):
    note = w.note("N")
    tasks = [w.task(f"t{i}") for i in range(4)]
    for t in tasks:
        w.derive("task", t, note)
    w.derive("reminder", w.reminder("r"), note)
    ids = w.all_ids()
    first = w.edges(*ids)
    assert len(first["edges"]) == 5 == w.summary()["edges"]
    for _ in range(3):
        assert w.edges(*ids) == first and w.summary()["edges"] == 5
    doubled = w.edges(*ids, *ids, f"task:{tasks[0]}")
    assert doubled == first and len({e["id"] for e in doubled["edges"]}) == 5


def test_nothing_is_written_and_unprovenanced_records_get_no_edges(w):
    note, task = w.note("N"), w.task("unrelated task")
    before = (len(w.run(w.notepad.list_provenance([task, note]))), len(w.run(w.tasks.list_tasks())), len(w.run(w.planner.list_notes())))
    body = w.edges(f"note:{note}", f"task:{task}")
    assert body["edges"] == [] and "Nothing is inferred" in body["note"]
    assert before == (len(w.run(w.notepad.list_provenance([task, note]))), len(w.run(w.tasks.list_tasks())), len(w.run(w.planner.list_notes())))


def test_edges_produced_by_the_real_accept_path_show_in_the_brain(monkeypatch):
    """The provenance written by NotepadService.accept (not a hand-made row) is what the Brain draws, for the owner's two real note/task pairs."""
    world = World(monkeypatch, flag=False)  # the flag is off here: historical provenance is still read

    async def go():
        svc = NotepadService(world.notepad, world.planner, world.tasks, lambda: _tz(), clock=lambda: NOW)
        out = {}
        for title, task_text in (("My Task for next week", "refactor clickhouse migration"), ("GIT", "spin up gitlab repo")):
            note = await world.planner.add_note(title, f"{task_text} please.")
            job = Job(note_id=note.id, note_title=title, snapshot_text=note.body, snapshot_hash=content_hash(note.body), note_updated_at=NOW, timezone="UTC", sensitivity=Privacy.WORK_PRIVATE,
                      inputs_hash=content_hash(note.body))
            await world.notepad.enqueue(job, force=False)
            await world.notepad.claim_next(NOW)
            quote = note.body
            proposal = Proposal(job_id=job.id, note_id=note.id, snapshot_hash=job.snapshot_hash, kind=Kind.TASK, text=task_text, evidence=quote, span_start=0, span_end=len(quote),
                                fingerprint=fingerprint(quote), sensitivity=Privacy.WORK_PRIVATE)
            await world.notepad.complete_job(job.id, [proposal], model="m", now=NOW)
            result = await svc.accept(proposal.id)
            out[title] = (note.id, result["record"]["id"], proposal.id)
        return out

    made = asyncio.run(go())
    ids = [f"note:{n}" for n, _, _ in made.values()] + [f"task:{t}" for _, t, _ in made.values()]
    edges = world.edges(*ids)["edges"]
    expected = {(f"task:{task}", f"note:{note}", f"derived_from:{proposal}") for note, task, proposal in made.values()}
    assert {(e["from"], e["to"], e["id"]) for e in edges} == expected and world.summary()["edges"] == 2


async def _tz():
    return "UTC"


def test_the_api_fails_closed_without_a_store(monkeypatch):
    """No provenance store (no database, none injected): the endpoint still answers, with no edges."""
    monkeypatch.delenv("NOTEPAD_PROCESSING_ENABLED", raising=False)
    app = create_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(embed_fn=lambda t: [[0.0] * 384 for _ in t]), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False)
    c = TestClient(app)
    assert c.get("/brain/edges", params={"ids": "task:a,note:b"}).json()["edges"] == [] and c.get("/brain/summary").json()["edges"] == 0
