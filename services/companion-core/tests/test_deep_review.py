"""Phase 42C: the deep local review. A fake model manager stands in for the host process; the notices that tell the
owner Reachy is unavailable and online again are the acceptance criteria."""

import asyncio
import json
import re
import time

import httpx
import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.deep_review import (
    DeepReviewRunner,
    DeepReviewUnavailable,
    ManagerError,
)
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

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeManager:
    """Scriptable stand-in for ModelManagerClient. Swaps take a moment so the runner's watcher can observe them."""

    def __init__(self) -> None:
        self.state_name = "ready_t1"
        self.calls: list[str] = []
        self.fail_activate: ManagerError | None = None
        self.fail_restore: ManagerError | None = None
        self.swap_s = 0.06
        self.unload_after_s = 0.0  # how long after the request the fast model is actually unloaded

    async def state(self) -> dict:
        return {"state": self.state_name}

    async def activate_deep(self, lease_seconds: float) -> dict:
        self.calls.append("activate")
        await asyncio.sleep(self.unload_after_s)
        self.state_name = "switching_to_t2"  # the fast model is unloaded from here on
        await asyncio.sleep(self.swap_s)
        if self.fail_activate:
            self.state_name = "ready_t1"
            raise self.fail_activate
        self.state_name = "ready_t2"
        return {"state": "ready_t2"}

    async def restore(self) -> dict:
        self.calls.append("restore")
        if self.state_name == "ready_t1":
            return {"state": "ready_t1"}
        self.state_name = "restoring_t1"
        await asyncio.sleep(self.swap_s)
        if self.fail_restore:
            self.state_name = "failed"
            raise self.fail_restore
        self.state_name = "ready_t1"
        return {"state": "ready_t1"}

    async def aclose(self) -> None:
        return None


def runner(manager: FakeManager | None, compute=None):
    notices: list = []

    async def default_compute(meeting_id: str, task: str) -> dict:
        return {"suggestions": [{"segment": 1}, {"segment": 2}], "terms_used": 3}

    async def record(receipt) -> None:
        notices.append(receipt)

    return DeepReviewRunner(manager, compute or default_compute, record, poll_interval_s=0.01), notices


async def finish(job, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not job.finished and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert job.finished, f"job still {job.status}"


def texts(notices) -> list[str]:
    return [n.fields["Message"] for n in notices]


async def test_happy_path_announces_unavailable_then_online_and_keeps_the_result() -> None:
    manager = FakeManager()
    deep, notices = runner(manager)
    job = await deep.start("m1", "Weekly sync")
    assert job.status == "switching" and job.eta_seconds > 0
    await finish(job)
    assert job.status == "done" and job.reachy_online is True and job.reachy_unavailable is False
    assert len(job.result["suggestions"]) == 2 and job.error is None
    assert manager.calls == ["activate", "restore"] and manager.state_name == "ready_t1"
    kinds = [n.action_type for n in notices]
    assert kinds == ["deep_review.unavailable", "deep_review.completed"]
    assert "Reachy is unavailable" in texts(notices)[0] and "Weekly sync" in texts(notices)[0]
    assert "2 suggestions ready" in texts(notices)[1] and "Reachy is back online" in texts(notices)[1]
    assert all(n.notify for n in notices)  # both reach Telegram through the receipts loop


async def test_the_unavailable_notice_waits_until_the_fast_model_is_actually_unloaded() -> None:
    manager = FakeManager()
    manager.unload_after_s = 0.25
    deep, notices = runner(manager)
    job = await deep.start("m1", "Sync")
    await asyncio.sleep(0.1)
    assert notices == [] and job.reachy_unavailable is False  # asked, but the fast model is still serving
    for _ in range(100):
        if notices:
            break
        await asyncio.sleep(0.01)
    assert [n.action_type for n in notices] == ["deep_review.unavailable"] and job.reachy_unavailable is True
    await finish(job)


async def test_a_review_error_still_restores_the_fast_model_and_says_so() -> None:
    manager = FakeManager()

    async def broken(meeting_id: str, task: str) -> dict:
        raise RuntimeError("model produced nonsense")

    deep, notices = runner(manager, broken)
    job = await deep.start("m1", "Sync")
    await finish(job)
    assert job.status == "failed" and job.reachy_online is True and "nonsense" in job.error
    assert manager.calls == ["activate", "restore"] and manager.state_name == "ready_t1"
    assert [n.action_type for n in notices] == ["deep_review.unavailable", "deep_review.failed"]
    assert "briefly unavailable" in texts(notices)[1] and "online on the standard model" in texts(notices)[1]
    assert notices[1].status == "failed"


async def test_a_start_failure_that_never_took_reachy_offline_says_it_stayed_available() -> None:
    manager = FakeManager()
    manager.swap_s = 0.0

    async def refuse(lease: float) -> dict:
        raise ManagerError("deep container failed to launch", fast_tier_restored=True)

    manager.activate_deep = refuse  # the manager refused instantly: the fast model was never unloaded
    deep, notices = runner(manager)
    job = await deep.start("m1", "Sync")
    await finish(job)
    assert job.status == "failed" and job.reachy_online is True
    assert [n.action_type for n in notices] == ["deep_review.failed"]
    assert "stayed available" in texts(notices)[0]


async def test_a_restore_failure_is_an_offline_alert_not_a_success() -> None:
    manager = FakeManager()
    manager.fail_restore = ManagerError("could not restore the fast tier")
    deep, notices = runner(manager)
    job = await deep.start("m1", "Sync")
    await finish(job)
    assert job.status == "failed" and job.reachy_online is False and job.reachy_unavailable is True
    assert [n.action_type for n in notices] == ["deep_review.unavailable", "deep_review.offline"]
    assert "OFFLINE" in texts(notices)[1] and "manual recovery" in texts(notices)[1] and notices[1].status == "failed"
    assert job.result is not None  # the review itself still finished and its result is kept


async def test_only_one_review_at_a_time_and_only_when_the_manager_is_on_the_fast_tier() -> None:
    manager = FakeManager()
    manager.swap_s = 0.2
    deep, _ = runner(manager)
    job = await deep.start("m1", "Sync")
    with pytest.raises(DeepReviewUnavailable, match="already running"):
        await deep.start("m2", "Other")
    await finish(job)
    manager.state_name = "failed"
    with pytest.raises(DeepReviewUnavailable, match="failed"):
        await deep.start("m2", "Other")
    info = await deep.info()
    assert info.configured and not info.available and "failed" in info.reason


async def test_not_configured_is_reported_not_attempted() -> None:
    deep, notices = runner(None)
    info = await deep.info()
    assert info.configured is False and info.available is False and "not configured" in info.reason
    with pytest.raises(DeepReviewUnavailable, match="not configured"):
        await deep.start("m1", "Sync")
    assert notices == []


async def test_an_unreachable_manager_is_reported_with_its_reason() -> None:
    manager = FakeManager()

    async def down() -> dict:
        raise ManagerError("the model manager is not reachable (ConnectError)")

    manager.state = down
    info = await runner(manager)[0].info()
    assert info.available is False and "not reachable" in info.reason


# ---- over HTTP, with the real suggestion pipeline on a stub model --------------------------------------------

SEGMENTS = [
    {"start": 0.0, "end": 3.0, "text": "And codex, and codex."},
    {"start": 3.0, "end": 5.0, "text": "And germanite."},
]


def stub_llm(request: httpx.Request) -> httpx.Response:
    system = json.loads(request.content)["messages"][0]["content"]
    if "option number" in system:
        quoted = re.search(r'Quoted words: "([^"]+)"', json.loads(request.content)["messages"][1]["content"])[1]
        return httpx.Response(200, json={"choices": [{"message": {"content": "1" if quoted == "germanite" else "9"}}]})
    return httpx.Response(200, json={"choices": [{"message": {"content": "[]"}}]})


def make_client(manager: FakeManager | None):
    store = InMemoryMeetingStore()

    async def seed() -> str:
        meeting = await store.create_meeting(title="AI tools", audio=b"x", source_filename="m.m4a", content_type="audio/mp4")
        store._touch(meeting, transcript_segments=SEGMENTS, status="complete")
        bare = await store.create_meeting(title="Bare", audio=b"x", source_filename="b.m4a", content_type="audio/mp4")
        return meeting.id, bare.id

    ids = asyncio.run(seed())
    client = TestClient(create_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(),
        meeting_store=store, run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, llm_transport=httpx.MockTransport(stub_llm), model_manager_client=manager,
    ))
    client.put("/settings/llm", json={"local": {"base_url": "http://vllm/v1", "model": "reachy-local"}})
    client.post("/meeting-terms", json={"term": "Gemini"})
    return client, ids


def test_the_routes_run_a_review_end_to_end_and_queue_telegram_notices() -> None:
    manager = FakeManager()
    client, (meeting_id, _) = make_client(manager)
    with client:
        info = client.get("/deep-review/info").json()
        assert info["configured"] and info["available"] and info["eta_seconds"] > 0
        started = client.post(f"/meetings/{meeting_id}/corrections/deep-review")
        assert started.status_code == 202 and started.json()["status"] == "switching"
        job_id = started.json()["id"]
        for _ in range(200):
            job = client.get(f"/deep-review/{job_id}").json()
            if job["status"] in ("done", "failed"):
                break
            time.sleep(0.02)
        assert job["status"] == "done" and job["reachy_online"] is True
        assert any(s["original"] == "germanite" and s["suggested"] == "Gemini" for s in job["result"]["suggestions"])
        assert client.get("/deep-review/current").json()["id"] == job_id
        pending = client.get("/receipts/pending").json()
        texts_ = [p["text"] for p in pending]
        assert any("Reachy is unavailable" in t for t in texts_) and any("Reachy is back online" in t for t in texts_)
        assert client.get("/receipts/pending").json() == []  # claim-once: Telegram gets each exactly once
        assert client.get("/deep-review/info").json()["available"] is True  # and the next review can start


def test_the_routes_refuse_what_cannot_run() -> None:
    client, (meeting_id, bare_id) = make_client(FakeManager())
    with client:
        assert client.post("/meetings/nope/corrections/deep-review").status_code == 404
        assert client.post(f"/meetings/{bare_id}/corrections/deep-review").status_code == 409  # no transcript
        assert client.get("/deep-review/missing").status_code == 404
        assert client.get("/deep-review/current").json() is None
    off, (meeting_id, _) = make_client(None)
    with off:
        assert off.get("/deep-review/info").json()["configured"] is False
        response = off.post(f"/meetings/{meeting_id}/corrections/deep-review")
        assert response.status_code == 409 and "not configured" in response.json()["detail"]
