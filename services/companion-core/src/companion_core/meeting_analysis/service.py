"""Phase 31: enqueue, process, review and commit meeting analysis. Deterministic code around one narrow model call (extract only); the model never writes.

It follows Phase 49's NotepadService step for step (docs/phase-31.md section 3) and reuses its runner: enqueue snapshots the transcript and returns at once, a bounded runner
extracts later, and `accept` is the only path from an action candidate to a task. It claims the item (pending -> accepting), creates the task under an id derived from the item (so a
retry, a double click or a crash cannot create a second one), writes the existing receipt, then closes the item. Every step is safe to run again."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

import psycopg

from companion_core.meeting_analysis import extraction
from companion_core.meeting_analysis.models import (
    MAX_CHUNKS,
    MAX_TEXT,
    PROMPT_VERSION,
    RECEIPT_NAMESPACE,
    Item,
    ItemKind,
    ItemStatus,
    Run,
    RunStatus,
    Seg,
    action_record_id,
    utcnow,
)
from companion_core.meeting_analysis.store import OPEN_ITEMS, MeetingAnalysisStore
from companion_core.meetings.corrections import current_text
from companion_core.meetings.models import READY_FOR_OUTPUTS, Meeting
from companion_core.meetings.outputs import display_name, speakers
from companion_core.notepad_processing.extraction import locate
from companion_core.notepad_processing.models import content_hash
from companion_core.privacy_classifier import classify_privacy
from shared.models.receipt import ActionReceipt
from shared.models.response import Privacy

log = logging.getLogger("companion_core.meeting_analysis")

ENABLED_FLAG = "MEETING_ANALYSIS_ENABLED"
CONCURRENCY_ENV = "MEETING_ANALYSIS_CONCURRENCY"
RUN_TIMEOUT_SECONDS = 600.0
_RANK = {Privacy.PUBLIC: 0, Privacy.WORK_PRIVATE: 1, Privacy.SENSITIVE: 2}

Provider = Callable[[], Awaitable[tuple[extraction.Ask, str] | None]]


def enabled() -> bool:
    return os.environ.get(ENABLED_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


class AnalysisError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def snapshot(meeting: Meeting) -> list[Seg]:
    """The transcript as the owner reads it now: accepted corrections applied, speaker names as displayed, segments the recording check flagged as silence marked. Empty lines are skipped."""
    who = speakers(meeting)
    gaps = set((meeting.audio_gaps or {}).get("segments", []))
    out: list[Seg] = []
    for index, segment in enumerate(meeting.transcript_segments or []):
        text = current_text(meeting, index)
        if not text:
            continue
        label = who[index] if index < len(who) else None
        out.append(Seg(index=index, start=float(segment.get("start", 0)), end=float(segment.get("end", segment.get("start", 0))), text=text,
                       speaker=display_name(meeting, label) if label else None, gap=index in gaps))
    return out


def transcript_hash(segments: list[Seg]) -> str:
    return content_hash("\n".join(f"{s.index}|{s.start}|{s.end}|{s.speaker}|{s.text}" for s in segments))


def default_task_text(item: Item) -> str:
    """The task an action becomes unless the owner edits it: the action, prefixed with the person it names (a task has no owner field) and followed by the time words as spoken."""
    text = item.text
    if item.assignee:
        text = f"{item.assignee}: {text}"
    if item.stated_time and item.stated_time.casefold() not in text.casefold():
        text = f"{text} ({item.stated_time})"
    return text[:MAX_TEXT]


def state_of(run: Run | None, items: list[Item]) -> str:
    if run is None:
        return "not_analysed"
    if run.status is RunStatus.QUEUED:
        return "queued"
    if run.status is RunStatus.PROCESSING:
        return "processing"
    if run.status is RunStatus.FAILED:
        return "failed"
    return "review_required" if any(i.status in OPEN_ITEMS for i in items) else "completed"


@dataclass
class MeetingAnalysisService:
    store: MeetingAnalysisStore
    meetings: object  # the meeting store
    tasks: object
    planner: object  # receipts
    timezone: Callable[[], Awaitable[str]]
    provider: Provider | None = None
    clock: Callable[[], datetime] = utcnow
    counters: dict[str, int] = None  # type: ignore[assignment]
    wake: asyncio.Event = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.counters = {}
        self.wake = asyncio.Event()

    def _count(self, key: str, n: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + n

    async def _ready_meeting(self, meeting_id: str) -> Meeting:
        meeting = await self.meetings.get_meeting(meeting_id)
        if meeting is None:
            raise AnalysisError(404, "No such meeting")
        return meeting

    # -- enqueue and status ------------------------------------------------------------------------------------------------

    async def enqueue(self, meeting_id: str, *, force: bool = False, expected_hash: str | None = None) -> dict:
        meeting = await self._ready_meeting(meeting_id)
        if meeting.status not in READY_FOR_OUTPUTS or not meeting.transcript_segments:
            raise AnalysisError(409, "The transcript is not ready yet")
        segments = snapshot(meeting)
        if not segments:
            raise AnalysisError(422, "The transcript is empty")
        if len(extraction.chunks(segments)) > MAX_CHUNKS:
            raise AnalysisError(422, "The transcript is too long to analyse")
        digest = transcript_hash(segments)
        if expected_hash is not None and expected_hash != digest:
            raise AnalysisError(409, "The transcript changed since you opened it; reload it")
        run = Run(meeting_id=meeting.id, meeting_title=meeting.title, transcript_hash=digest, segments=segments, meeting_started_at=meeting.started_at, timezone=await self.timezone(),
                  sensitivity=meeting.sensitivity, project_scope=meeting.project_scope, reprocess=force, created_at=self.clock(),
                  inputs_hash=content_hash(f"{digest}|{PROMPT_VERSION}"))
        _, created = await self.store.enqueue(run, force=force)
        if created:
            self._count("enqueued")
            self.wake.set()
        return {"created": created, **await self.status(meeting_id)}

    async def status(self, meeting_id: str) -> dict:
        meeting = await self.meetings.get_meeting(meeting_id)
        run = await self.store.latest_run(meeting_id)
        items = await self.store.list_items(meeting_id=meeting_id)
        now = snapshot(meeting) if meeting is not None and meeting.transcript_segments else None
        current = transcript_hash(now) if now is not None else None
        texts = {s.index: s.text for s in now} if now is not None else None
        who = {s.index: s.speaker for s in now} if now is not None else None
        return {
            "meeting_id": meeting_id,
            "state": state_of(run, items),
            "run": run.view() if run else None,
            "transcript_changed_since_run": bool(run and current is not None and current != run.transcript_hash),
            "items": [self._view(i, texts, who) for i in items],
        }

    @staticmethod
    def _view(item: Item, current: dict[int, str] | None, speakers: dict[int, str | None] | None = None) -> dict:
        """`current` maps segment index to the segment's text as the transcript reads now. An item is flagged only when its own quote is no longer in its own segments (a correction touched
        them), not whenever any line of the meeting was edited."""
        data = item.model_dump(mode="json", exclude={"fingerprint", "final_text"})
        data["source_changed"] = current is not None and not all(
            all(n in current for n in e.segments or [e.segment]) and locate(" ".join(current[n] for n in e.segments or [e.segment]), e.quote) is not None for e in item.evidence)
        # The name printed on the evidence was the speaker's name when the analysis ran; the owner may have renamed that speaker since.
        data["attribution_changed"] = speakers is not None and any(e.speaker != speakers.get(e.segment, e.speaker) for e in item.evidence)
        if item.kind is ItemKind.ACTION:
            data["task_text"] = item.final_text or default_task_text(item)
        return data

    async def retry(self, run_id: str) -> dict:
        run, outcome = await self.store.retry_run(run_id, now=self.clock())
        if outcome == "missing":
            raise AnalysisError(404, "No such run")
        if outcome == "not_failed":
            raise AnalysisError(409, "Only a failed run can be retried")
        if outcome == "active":
            raise AnalysisError(409, "This meeting is already being analysed")
        self.wake.set()
        return await self.status(run.meeting_id)

    async def pending(self) -> dict:
        """Every action candidate awaiting a decision, with its meeting's title."""
        rows = await self.store.list_items(statuses=(*OPEN_ITEMS,))
        titles: dict[str, str | None] = {}
        texts: dict[str, dict[int, str] | None] = {}
        names: dict[str, dict[int, str | None] | None] = {}
        out = []
        for i in rows:
            if i.meeting_id not in titles:
                meeting = await self.meetings.get_meeting(i.meeting_id)
                titles[i.meeting_id] = meeting.title if meeting else None
                shown = snapshot(meeting) if meeting is not None and meeting.transcript_segments else None
                texts[i.meeting_id] = {s.index: s.text for s in shown} if shown is not None else None
                names[i.meeting_id] = {s.index: s.speaker for s in shown} if shown is not None else None
            out.append({**self._view(i, texts[i.meeting_id], names[i.meeting_id]), "meeting_title": titles[i.meeting_id]})
        return {"items": out}

    async def provenance(self, record_id: str) -> dict | None:
        """Where a task came from: the meeting, the segments and the quotes. None when the task was not made from a meeting action."""
        item = await self.store.item_for_record(record_id)
        if item is None:
            return None
        meeting = await self.meetings.get_meeting(item.meeting_id)
        return {"record_id": record_id, "item_id": item.id, "meeting_id": item.meeting_id, "meeting_title": meeting.title if meeting else None,
                "transcript_hash": item.transcript_hash, "evidence": [e.model_dump(mode="json") for e in item.evidence]}

    # -- the runner ----------------------------------------------------------------------------------------------------------

    async def process_next(self) -> bool:
        """Claim and process one run. Returns whether there was one. Never raises."""
        run = await self.store.claim_next(self.clock())
        if run is None:
            return False
        try:
            offered = await self.provider() if self.provider is not None else None
            if offered is None:
                raise extraction.ExtractionFailed("model_unavailable")
            ask, model = offered
            async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
                items, rejected = await extraction.extract(run, ask, model=model)
            added = await self.store.complete_run(run.id, items, model=model, rejected=rejected, now=self.clock())
            self._count("succeeded")
            self._count("items", added)
            for reason, n in rejected.items():
                self._count(f"rejected_{reason}", n)
        except extraction.ExtractionFailed as exc:
            await self._fail(run, exc.code)
        except TimeoutError:
            await self._fail(run, "timeout")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider errors can carry URLs or text: log the type only
            log.warning("meeting analysis failed: %s", type(exc).__name__)
            await self._fail(run, "model_unavailable" if type(exc).__name__ == "ProviderUnavailable" else "internal_error")
        return True

    async def _fail(self, run: Run, code: str) -> None:
        self._count(f"failed_{code}")
        await self.store.fail_run(run.id, code, now=self.clock())

    # -- review and commit ---------------------------------------------------------------------------------------------------

    async def accept(self, item_id: str, *, text: str | None = None) -> dict:
        """Confirm an action candidate: it becomes a task, once, with the meeting as provenance."""
        now = self.clock()
        item = await self.store.get_item(item_id)
        if item is None:
            raise AnalysisError(404, "No such item")
        if item.status is ItemStatus.ACCEPTED:
            return await self._result(item)  # a retry or a double click: the same task, nothing new
        if item.kind is not ItemKind.ACTION or item.status in (ItemStatus.DISMISSED, ItemStatus.NOTED):
            raise AnalysisError(409, "This item is not waiting for a decision")
        if item.status is ItemStatus.PENDING:
            final = " ".join((text if text is not None else default_task_text(item)).split())
            if not final or len(final) > MAX_TEXT:
                raise AnalysisError(422, f"The text must be between 1 and {MAX_TEXT} characters")
            level = max(item.sensitivity, classify_privacy(final), key=_RANK.__getitem__)
            edited = final != default_task_text(item)
        else:  # accepting: a retry; the values stored at the first claim are the ones used
            final, level, edited = item.final_text, item.sensitivity, item.edited
        claim = await self.store.claim_accept(item_id, text=final, sensitivity=level, edited=edited, now=now)
        if claim.outcome == "done":
            return await self._result(claim.item)
        if claim.outcome == "in_progress":
            raise AnalysisError(409, "This item is being saved; try again in a moment")
        if claim.outcome == "missing":
            raise AnalysisError(404, "No such item")
        if claim.outcome != "claimed":
            raise AnalysisError(409, "This item can no longer be accepted")
        return await self._finish(claim.item)

    async def _finish(self, item: Item) -> dict:
        """Create the task once, write the receipt once, then close the item. Safe to run again after any interruption."""
        record_id = action_record_id(item.id)
        if await self.tasks.get_task(record_id) is None:
            try:
                await self.tasks.add_task(item.final_text, sensitivity=item.sensitivity, project_scope=item.project_scope, record_id=record_id)
            except (psycopg.errors.UniqueViolation, ValueError):
                pass  # a concurrent finisher created it first: same id, same task
        await self._receipt(item, record_id)
        done = await self.store.finish_accept(item.id, "task", record_id, now=self.clock())
        if done is None:
            raise AnalysisError(409, "This item can no longer be accepted")
        self._count("accepted")
        return await self._result(done)

    async def _receipt(self, item: Item, record_id: str) -> None:
        """The existing task.created receipt, with an id derived from the item so a retry cannot write a second one. A failure never undoes the accept (ADR 0028)."""
        receipt = ActionReceipt(id=str(uuid.uuid5(RECEIPT_NAMESPACE, item.id)), action_type="task.created", source_channel="web", object_type="task", object_id=record_id,
                                fields={"Task": item.final_text, "From": "reviewed meeting action"}, notify=False)
        try:
            await self.planner.add_receipt(receipt)
        except psycopg.errors.UniqueViolation:
            return
        except Exception:
            log.exception("could not record the receipt for an accepted meeting action")

    async def _result(self, item: Item) -> dict:
        return {"item": self._view(item, None), "record": {"kind": item.record_kind, "id": item.record_id} if item.record_id else None}

    async def dismiss(self, item_id: str) -> dict:
        decision = await self.store.dismiss(item_id, now=self.clock())
        if decision.outcome == "missing":
            raise AnalysisError(404, "No such item")
        if decision.outcome == "closed":
            raise AnalysisError(409, "This item was already decided")
        return await self._result(decision.item)

    async def meeting_deleted(self, meeting_id: str) -> None:
        with contextlib.suppress(Exception):
            await self.store.drop_meeting(meeting_id)

    async def reconcile(self) -> int:
        """Finish accepts a crash interrupted: take over each stale `accepting` item and run the same idempotent finish."""
        n = 0
        for item_id in await self.store.stale_accepting(self.clock()):
            with contextlib.suppress(AnalysisError):
                await self.accept(item_id)
                n += 1
        return n

    def summary(self) -> dict[str, int]:
        return dict(self.counters)
