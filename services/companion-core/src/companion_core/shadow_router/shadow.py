"""Shadow pipeline: semantic router -> few-shot extractor -> deterministic validator -> record the proposed outcome only.

Hard contract (owner decision 2026-10-05):
- no tool execution, and no change to the response, consent, draft, memory, task or robot state;
- runs after the production reply is final, as a background task; a failure or a busy extractor only increments a counter;
- robot routes are not extracted: the production Qwen classifier (`command_suggestion.classify`) stays authoritative for them;
- `needs_clarification` records a reason category only; nothing is synthesised into the live conversation;
- memory.forget / tasks.complete always retain the resolved target (validated value) so what would have been confirmed can be compared.
Extraction is offline by default (SHADOW_EXTRACT_MODE): the live path then calls only the router sidecar, so the production model is never touched.
Trial bounds: a bounded queue (oldest job dropped when full) and an optional turn cap. Privacy: the file is created 0600; the utterance is written only with SHADOW_ROUTER_LOG_TEXT=true, and never for a SENSITIVE-labelled turn.
Observable counters here are `would_execute` / `withheld`; `unsafe_would_execute` and `safe_but_withheld` need a grade per record and come from
tools/shadow_router_report.py."""
from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import logging
import os
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from companion_core.shadow_router import validator
from companion_core.shadow_router.extractor import extract
from shared.models.llm import LLMConfig, ProviderConfig

log = logging.getLogger("companion_core.shadow_router")
_NO_EXTRACT = {"none", "unsupported", "robot.standby", "robot.resume", "coding.status", "coding.usage"}
_RETAIN_TARGET = {"memory.forget": "query", "tasks.complete": "task"}


def _category(reason: str) -> str:
    """'query:ungrounded:foo,bar' -> 'query:ungrounded' (model-proposed words never reach the record)."""
    parts = reason.split(":")
    return ":".join(parts[:2])


@dataclass
class ShadowTurn:
    """Snapshot taken after the production reply is final. Plain data only: no stores, no handles."""
    session_id: str
    text: str
    channel: str
    modality: str
    privacy: str  # production privacy label of the turn
    production_handler: str  # which production branch answered, e.g. "tasks.complete", "generic_chat", "slash_command"
    production_suggestion: str | None = None  # robot intent the production classifier suggested, if any
    llm: LLMConfig | None = None


@dataclass
class ShadowPipeline:
    router_url: str
    log_path: str
    log_text: bool = False
    extract_mode: str = "offline"  # offline: live path calls only the router and marks extraction pending; live: also call the extractor in the turn
    max_turns: int = 0  # trial bound: stop recording after this many accepted turns (0 = unlimited)
    queue_size: int = 0  # pending shadow jobs (0 = 16 offline, 3 live); beyond this the OLDEST is dropped so production never waits behind shadow work
    router_transport: httpx.AsyncBaseTransport | None = None
    llm_transport: httpx.AsyncBaseTransport | None = None
    counters: Counter = field(default_factory=Counter)
    _pending: collections.deque = field(default_factory=collections.deque)
    _worker: asyncio.Task | None = None
    _accepted: int = 0

    def submit(self, turn: ShadowTurn) -> None:
        """Best-effort and non-blocking: never raises, never awaits the pipeline, never builds a backlog."""
        if turn.production_handler == "slash_command":  # typed commands are authenticated and deterministic, nothing to compare
            return
        if self.max_turns and self._accepted >= self.max_turns:
            self.counters["trial_complete_skipped"] += 1
            return
        self._accepted += 1
        if len(self._pending) >= (self.queue_size or (3 if self.extract_mode == "live" else 16)):
            self._pending.popleft()  # drop the oldest shadow job
            self.counters["dropped_busy"] += 1
        self._pending.append(turn)
        if self._worker is None or self._worker.done():
            try:
                self._worker = asyncio.get_running_loop().create_task(self._drain_queue())
            except RuntimeError:
                self._pending.clear()

    async def _drain_queue(self) -> None:
        # One job at a time: the extractor shares the production model, so shadow work is serialized and bounded.
        while self._pending:
            await self._run(self._pending.popleft())

    async def drain(self) -> None:  # tests and shutdown
        if self._worker is not None:
            await asyncio.gather(self._worker, return_exceptions=True)

    async def _run(self, turn: ShadowTurn) -> None:
        try:
            await self._pipeline(turn)
        except Exception:  # noqa: BLE001 - the shadow path must never surface an error
            self.counters["shadow_error"] += 1
            log.warning("shadow router pipeline error", exc_info=False)

    async def _route(self, text: str) -> dict | None:
        try:
            async with httpx.AsyncClient(transport=self.router_transport, timeout=3.0, follow_redirects=False) as client:
                response = await client.post(self.router_url.rstrip("/") + "/route", json={"text": text})
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError):
            return None

    async def _pipeline(self, turn: ShadowTurn) -> None:
        self.counters["turns"] += 1
        if self.extract_mode not in ("offline", "live"):
            raise ValueError(f"SHADOW_EXTRACT_MODE must be offline or live, not {self.extract_mode!r}")
        routed = await self._route(turn.text)
        if routed is None:
            self.counters["router_error"] += 1
            return
        route = routed["route"]
        extraction: dict = {"status": "skipped"}
        verdict: validator.Validation | None = None
        if route not in _NO_EXTRACT and route in validator.SCHEMAS:
            provider: ProviderConfig | None = turn.llm.local if turn.llm else None  # local only, never cloud
            if self.extract_mode == "offline":
                extraction = {"status": "pending"}  # filled later by tools/shadow_router_extract.py with the same extractor and validator
            elif provider is None:
                extraction = {"status": "no_local_provider"}
            else:
                started = time.monotonic()
                proposed = await extract(provider, route, turn.text, transport=self.llm_transport)
                extraction = {"status": "ok" if proposed is not None else "error", "model": provider.model,
                              "ms": round((time.monotonic() - started) * 1000)}
                if proposed is None:
                    self.counters["extractor_error"] += 1
                else:
                    verdict = validator.validate(route, proposed, turn.text)
        action = "pending_extraction" if extraction["status"] == "pending" else self._proposed_action(route, verdict)
        self._count(route, verdict, action)
        self._write(turn, routed, extraction, verdict, action)

    @staticmethod
    def _proposed_action(route: str, verdict: validator.Validation | None) -> str:
        if route == "none":
            return "chat"
        if route == "unsupported":
            return "refuse_unsupported"
        if route.startswith("robot."):
            return "robot_suggestion_via_production_classifier"
        if route in ("coding.status", "coding.usage"):
            return f"read:{route}"
        if verdict is None:
            return "no_extraction"
        if verdict.status == "bulk_refused":
            return "refuse_bulk"
        if verdict.status == "needs_clarification":
            cats = sorted({_category(r) for r in verdict.reasons if ":" in r and not r.split(":")[1].startswith("dropped")})
            return "ask_clarification:" + ("+".join(cats) or "unspecified")
        return f"consent_gate:{route}" if route in validator.WRITE_ROUTES else f"read:{route}"

    def _count(self, route: str, verdict: validator.Validation | None, action: str) -> None:
        self.counters[f"route:{route}"] += 1
        if verdict is None:
            return
        if verdict.status == "ok":
            self.counters["would_execute"] += 1
            if route in validator.WRITE_ROUTES:
                self.counters["would_execute_write"] += 1
        elif verdict.status == "needs_clarification":
            self.counters["withheld"] += 1
            for r in verdict.reasons:
                if not r.split(":")[1].startswith("dropped"):
                    self.counters["withheld_reason:" + r.split(":")[1]] += 1
        else:
            self.counters["bulk_refused"] += 1

    def _write(self, turn: ShadowTurn, routed: dict, extraction: dict, verdict: validator.Validation | None, action: str) -> None:
        sensitive = turn.privacy == "sensitive"
        row = {
            "rid": uuid.uuid4().hex[:12],
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "session": hashlib.sha256(turn.session_id.encode()).hexdigest()[:12],
            "channel": turn.channel, "modality": turn.modality, "privacy": turn.privacy,
            "production": {"handler": turn.production_handler, "robot_suggestion": turn.production_suggestion},
            "router": {k: routed.get(k) for k in ("route", "confidence", "member_routes", "latency_ms")},
            "extraction": extraction,
            "validator": None if verdict is None else {"status": verdict.status, "reasons": [_category(r) for r in verdict.reasons]},
            "proposed_action": action,
            "text_sha256": hashlib.sha256(turn.text.encode()).hexdigest()[:16], "text_len": len(turn.text),
        }
        route = routed["route"]
        if verdict is not None and route in _RETAIN_TARGET and not sensitive:
            row["resolved_target"] = verdict.args.get(_RETAIN_TARGET[route])  # what would have been echoed back for confirmation
        if self.log_text and not sensitive:
            row["text"] = turn.text
            if verdict is not None:
                row["validated_args"] = verdict.args  # user words only; lets a blind grader's expected target be compared without unblinding
        fd = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as handle:
            handle.write(json.dumps(row) + "\n")


def shadow_from_env() -> ShadowPipeline | None:
    """Disabled unless SHADOW_ROUTER_ENABLED=true AND a router URL and log path are configured."""
    if (os.environ.get("SHADOW_ROUTER_ENABLED") or "").lower() != "true":
        return None
    url, path = os.environ.get("SHADOW_ROUTER_URL"), os.environ.get("SHADOW_ROUTER_LOG_PATH")
    if not url or not path:
        log.warning("SHADOW_ROUTER_ENABLED is set but SHADOW_ROUTER_URL / SHADOW_ROUTER_LOG_PATH is missing; shadow router stays off")
        return None
    return ShadowPipeline(
        router_url=url, log_path=path, log_text=(os.environ.get("SHADOW_ROUTER_LOG_TEXT") or "").lower() == "true",
        extract_mode=(os.environ.get("SHADOW_EXTRACT_MODE") or "offline").lower(), max_turns=int(os.environ.get("SHADOW_ROUTER_MAX_TURNS") or 0), queue_size=int(os.environ.get("SHADOW_ROUTER_QUEUE_SIZE") or 0),
    )
