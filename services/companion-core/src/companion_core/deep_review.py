"""Deep local review (Phase 42C, ADR 0031): run a task on the larger local model, then bring the fast one back.

The model manager (a host process; see services/model-manager) owns which model is loaded. This module only asks it
for the deep tier, runs the work, always asks for the fast tier back, and tells the owner what is happening: a
Telegram notice when the fast model is unloaded and another when Reachy is back online, through the existing action
receipts. Jobs are held in memory: if core restarts mid-review the manager's lease still restores the fast tier."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from shared.models.deep_review import DeepReviewInfo, DeepReviewJob
from shared.models.receipt import ActionReceipt

log = logging.getLogger(__name__)

# Measured 2026-10-07 (docs/phase-42.md): about 115 s to load the 14B, a short review, about 80 s to restore the 7B.
ETA_SECONDS = 330
LEASE_SECONDS = 1200.0
KEPT_JOBS = 10


class ManagerError(Exception):
    def __init__(self, message: str, *, fast_tier_restored: bool | None = None) -> None:
        super().__init__(message)
        self.fast_tier_restored = fast_tier_restored


class DeepReviewUnavailable(Exception):
    """The request cannot start: not configured, the manager is busy or degraded, or a review is already running."""


class ModelManagerClient:
    """HTTP client for the model manager. Calls block for as long as a model swap takes."""

    def __init__(self, base_url: str, token: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url, transport=transport, headers={"Authorization": f"Bearer {token}"}, timeout=10.0
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def state(self) -> dict[str, Any]:
        try:
            response = await self._client.get("/state")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ManagerError(f"the model manager is not reachable ({type(exc).__name__})") from None
        return response.json()

    async def activate_deep(self, lease_seconds: float) -> dict[str, Any]:
        return await self._post("/tier/activate", {"tier": "t2", "lease_seconds": lease_seconds}, timeout=900.0)

    async def restore(self) -> dict[str, Any]:
        return await self._post("/tier/restore", None, timeout=1500.0)

    async def _post(self, path: str, body: dict | None, *, timeout: float) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=body, timeout=timeout)
        except httpx.HTTPError as exc:
            raise ManagerError(f"the model manager did not answer ({type(exc).__name__})") from None
        if response.is_success:
            return response.json()
        detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else None
        if isinstance(detail, dict):
            raise ManagerError(str(detail.get("error", "request failed")), fast_tier_restored=detail.get("fast_tier_restored"))
        raise ManagerError(str(detail or f"request failed ({response.status_code})"))


Compute = Callable[[str, str], Awaitable[dict[str, Any]]]

# How each task is named in the owner-facing notices.
TASK_LABELS = {"corrections": "deep review", "summary": "deep summary", "minutes": "deep minutes"}
Record = Callable[[ActionReceipt], Awaitable[None]]


class DeepReviewRunner:
    def __init__(
        self, manager: ModelManagerClient | None, compute: Compute, record: Record, *,
        poll_interval_s: float = 1.5, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._manager, self._compute, self._record = manager, compute, record
        self._poll, self._sleep = poll_interval_s, sleep
        self._jobs: list[DeepReviewJob] = []
        self._tasks: set[asyncio.Task[None]] = set()

    # ---- queries -----------------------------------------------------------------------------------------

    def current(self) -> DeepReviewJob | None:
        return self._jobs[-1] if self._jobs else None

    def get(self, job_id: str) -> DeepReviewJob | None:
        return next((job for job in self._jobs if job.id == job_id), None)

    def _active(self) -> DeepReviewJob | None:
        job = self.current()
        return job if job and not job.finished else None

    async def info(self) -> DeepReviewInfo:
        if self._manager is None:
            return DeepReviewInfo(configured=False, available=False, reason="the model manager is not configured", eta_seconds=ETA_SECONDS)
        if self._active():
            return DeepReviewInfo(configured=True, available=False, reason="a deep review is already running", eta_seconds=ETA_SECONDS)
        try:
            state = (await self._manager.state())["state"]
        except ManagerError as exc:
            return DeepReviewInfo(configured=True, available=False, reason=str(exc), eta_seconds=ETA_SECONDS)
        if state != "ready_t1":
            return DeepReviewInfo(configured=True, available=False, reason=f"the model manager is {state.replace('_', ' ')}", eta_seconds=ETA_SECONDS)
        return DeepReviewInfo(configured=True, available=True, eta_seconds=ETA_SECONDS)

    # ---- starting a job ----------------------------------------------------------------------------------

    async def start(self, meeting_id: str, meeting_title: str, task: str = "corrections") -> DeepReviewJob:
        info = await self.info()
        if not info.available:
            raise DeepReviewUnavailable(info.reason or "deep review is unavailable")
        job = DeepReviewJob(meeting_id=meeting_id, meeting_title=meeting_title, task=task, eta_seconds=ETA_SECONDS,
                            stage="Unloading the standard model and loading the larger one")
        self._jobs = [*self._jobs, job][-KEPT_JOBS:]
        task = asyncio.ensure_future(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def close(self) -> None:
        """Core shutdown: stop watching; the manager's lease restores the fast tier on its own."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ---- the job -----------------------------------------------------------------------------------------

    def _touch(self, job: DeepReviewJob, **changes: Any) -> None:
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = datetime.now(UTC)

    async def _notify(self, job: DeepReviewJob, kind: str, text: str, *, ok: bool = True) -> None:
        await self._record(ActionReceipt(
            action_type=f"deep_review.{kind}", status="success" if ok else "failed", source_channel="system",
            object_type="meeting", object_id=job.meeting_id, fields={"Message": text}, notify=True,
        ))

    async def _watch_unload(self, job: DeepReviewJob, announced: asyncio.Event) -> None:
        """Tell the owner the moment the fast model has actually been unloaded, not merely when we asked."""
        assert self._manager is not None
        while not announced.is_set():
            await self._sleep(self._poll)
            try:
                state = (await self._manager.state())["state"]
            except ManagerError:
                continue
            if state != "ready_t1" and not job.reachy_unavailable and not job.finished:
                self._touch(job, reachy_unavailable=True)
                announced.set()
                minutes = max(1, round(job.eta_seconds / 60))
                await self._notify(
                    job, "unavailable",
                    f"Reachy is unavailable: a {TASK_LABELS.get(job.task, 'deep review')} of “{job.meeting_title}” is running on the larger "
                    f"local model. It should take about {minutes} minutes; I'll message you when Reachy is back online.",
                )

    async def _run(self, job: DeepReviewJob) -> None:
        assert self._manager is not None
        announced = asyncio.Event()
        watcher = asyncio.ensure_future(self._watch_unload(job, announced))
        error: str | None = None
        try:
            await self._manager.activate_deep(LEASE_SECONDS)
            self._touch(job, status="reviewing", stage="Reviewing the transcript with the larger model", reachy_unavailable=True)
            # The deep model may have been up for a moment before the watcher noticed.
            if not announced.is_set():
                announced.set()
                await self._notify(job, "unavailable", f"Reachy is unavailable: a {TASK_LABELS.get(job.task, 'deep review')} of “{job.meeting_title}” is running on the larger local model.")
            self._touch(job, result=await self._compute(job.meeting_id, job.task))
        except ManagerError as exc:
            error = f"the larger model could not be started: {exc}"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail = getattr(exc, "detail", None)
            error = f"the review failed: {detail or exc}"
            log.exception("deep review failed")
        finally:
            watcher.cancel()
        await self._finish(job, error, was_announced=announced.is_set())

    async def _finish(self, job: DeepReviewJob, error: str | None, *, was_announced: bool) -> None:
        assert self._manager is not None
        self._touch(job, status="restoring", stage="Reloading the standard model")
        online, restore_error = True, None
        try:
            await self._manager.restore()
        except ManagerError as exc:
            online, restore_error = False, str(exc)
        self._touch(job, reachy_unavailable=not online, reachy_online=online,
                    status="failed" if (error or not online) else "done",
                    stage="Reachy is back online" if online else "Reachy's standard model could not be reloaded",
                    error=(error or restore_error))
        title = job.meeting_title
        label = TASK_LABELS.get(job.task, "deep review")
        if not online:
            await self._notify(job, "offline",
                               f"Reachy is OFFLINE: the standard model could not be reloaded after the {label} of “{title}” "
                               f"({restore_error}). It needs manual recovery on the homelab (python -m model_manager restore).", ok=False)
        elif error:
            was_down = "Reachy was briefly unavailable and " if was_announced else "Reachy stayed available and "
            await self._notify(job, "failed", f"The {label} of “{title}” did not complete ({error}). {was_down}is online on the standard model.", ok=False)
        else:
            if job.task == "corrections":
                count = len((job.result or {}).get("suggestions", []))
                ready = f"{count} {'suggestion' if count == 1 else 'suggestions'} ready"
            else:
                ready = f"the {job.task} is ready"
            await self._notify(job, "completed", f"The {label} of “{title}” is complete: {ready}. Reachy is back online.")
