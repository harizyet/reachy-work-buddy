"""The read-only ICS feed (ADR 0035): configuration, the last good snapshot, classification and recording reminders.

Nothing here writes to the calendar. The owner's feed URL is a credential: it is stored through the encrypted secret store (feed_store.py), never returned by any method here,
and never logged. A refresh that fails keeps the last good snapshot and records a fixed error code; the snapshot says how old it is.

The snapshot holds `EventFacts` (no description). Classification, overrides and the reminder decision are computed when events are read, from the current rules, so changing a
rule or an override takes effect at once and needs no new download.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from companion_core.calendar.classify import (
    Classification,
    ClassificationRules,
    EventClass,
    EventFacts,
    apply_override,
    classify,
    reminder_decision,
)
from companion_core.calendar.ics import FeedError, parse_feed
from companion_core.calendar.models import CalendarEvent
from companion_core.calendar.safe_fetch import FeedFetcher
from companion_core.calendar.store import CalendarStore

log = logging.getLogger("companion_core.calendar.feed")

MAX_OVERRIDES = 500
UNTITLED = "(untitled event)"
HIDDEN_TITLE = "Busy"


class FeedConfig(BaseModel):
    refresh_minutes: int = Field(default=15, ge=5, le=1440)
    lead_minutes: int = Field(default=5, ge=1, le=120)  # how long before a meeting the recording reminder is due
    horizon_days: int = Field(default=60, ge=7, le=180)  # how far ahead the snapshot keeps occurrences
    device_horizon_hours: int = Field(default=72, ge=6, le=168)  # how far ahead the phone is given reminders to schedule
    timezone: str | None = None  # None means the persona's timezone; all-day dates and floating times are read in it
    rules: ClassificationRules = Field(default_factory=ClassificationRules)

    @field_validator("timezone")
    @classmethod
    def _zone(cls, value: str | None) -> str | None:
        if value:
            try:
                ZoneInfo(value)
            except Exception:  # noqa: BLE001 - ZoneInfoNotFoundError is not a ValueError, and a validator must raise one
                raise ValueError("unknown timezone") from None
        return value or None


class Snapshot(BaseModel):
    facts: list[EventFacts] = Field(default_factory=list)
    fetched_at: datetime
    window_start: datetime
    window_end: datetime
    truncated: bool = False
    skipped: int = 0
    revision: str = ""


class FeedStatus(BaseModel):
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    error: str | None = None  # a fixed code from safe_fetch / ics, never text from the feed
    consecutive_failures: int = 0
    host: str | None = None  # the host only; the path of a feed URL is part of the secret


class FeedState(BaseModel):
    configured: bool = False
    config: FeedConfig = Field(default_factory=FeedConfig)
    overrides: dict[str, str] = Field(default_factory=dict)
    snapshot: Snapshot | None = None
    status: FeedStatus = Field(default_factory=FeedStatus)


class FeedStore(Protocol):
    async def load(self) -> FeedState: ...
    async def get_url(self) -> str | None: ...
    async def set_url(self, url: str, host: str) -> None: ...
    async def clear(self) -> None: ...
    async def save_config(self, config: FeedConfig) -> None: ...
    async def save_overrides(self, overrides: dict[str, str]) -> None: ...
    async def save_snapshot(self, snapshot: Snapshot, status: FeedStatus) -> None: ...
    async def save_status(self, status: FeedStatus) -> None: ...


class InMemoryFeedStore:
    """For tests and for a core run without a database. The URL lives only in this object."""

    def __init__(self) -> None:
        self._url: str | None = None
        self._state = FeedState()

    async def load(self) -> FeedState:
        return self._state.model_copy(deep=True)

    async def get_url(self) -> str | None:
        return self._url

    async def set_url(self, url: str, host: str) -> None:
        self._url = url
        self._state = self._state.model_copy(update={"configured": True, "snapshot": None, "status": FeedStatus(host=host)})

    async def clear(self) -> None:
        self._url = None
        self._state = FeedState(config=self._state.config, overrides=self._state.overrides)

    async def save_config(self, config: FeedConfig) -> None:
        self._state = self._state.model_copy(update={"config": config})

    async def save_overrides(self, overrides: dict[str, str]) -> None:
        self._state = self._state.model_copy(update={"overrides": dict(overrides)})

    async def save_snapshot(self, snapshot: Snapshot, status: FeedStatus) -> None:
        self._state = self._state.model_copy(update={"snapshot": snapshot, "status": status})

    async def save_status(self, status: FeedStatus) -> None:
        self._state = self._state.model_copy(update={"status": status})


def display_event(facts: EventFacts, classification: Classification, blocked: str | None) -> CalendarEvent:
    hidden = facts.redacted
    missing = not hidden and not facts.title
    return CalendarEvent(
        id=facts.key, title=HIDDEN_TITLE if hidden else (facts.title or UNTITLED), start=facts.start, end=facts.end, location=None if hidden else facts.location,
        busy=not facts.transparent and facts.status != "cancelled" and facts.owner_response != "declined",
        all_day=facts.all_day, classification=classification.event_class.value, classification_basis=classification.basis.value,
        classification_reasons=classification.reasons, status=facts.status, response=facts.owner_response, redacted=hidden, title_missing=missing, source="ics",
        event_key=facts.key, series_key=facts.series_key, recurring=facts.recurring, remind=blocked is None, remind_blocked=blocked,
    )


def facts_from_event(event: CalendarEvent) -> EventFacts:
    """Classification input for an event that did not come from the feed (the local store, Google): only what it carries, so the answer rests on its title and all-day flag."""
    return EventFacts(
        key=event.id, series_key=event.id, source_uid=event.id, start=event.start, end=event.end, all_day=event.all_day, title=event.title, location=event.location,
        status=event.status, transparent=not event.busy,
    )


class CalendarFeedService:
    def __init__(
        self, store: FeedStore, fetcher: FeedFetcher, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        timezone: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self._store, self._fetcher, self._clock = store, fetcher, clock
        self._timezone = timezone
        self._lock = asyncio.Lock()
        self._state: FeedState | None = None  # core is the only writer, so this copy is the truth between writes

    async def _load(self) -> FeedState:
        if self._state is None:
            self._state = await self._store.load()
        return self._state

    def _invalidate(self) -> None:
        self._state = None

    async def _zone(self, state: FeedState) -> ZoneInfo:
        name = state.config.timezone
        if not name and self._timezone is not None:
            try:
                name = await self._timezone()
            except Exception:  # noqa: BLE001 - a persona lookup failure must not stop calendar reads
                name = None
        try:
            return ZoneInfo(name or "UTC")
        except Exception:  # noqa: BLE001
            return ZoneInfo("UTC")

    # --- configuration -------------------------------------------------------------------------------------------------------------------------------------

    def _brief(self, state: FeedState, now: datetime) -> dict:
        """Whether the feed is set up and how fresh the snapshot is. Never the URL; the host only."""
        status, config = state.status, state.config
        age = None if status.last_success_at is None else int((now - status.last_success_at).total_seconds())
        if not state.configured:
            freshness = "not_configured"
        elif age is None:
            freshness = "never"
        else:
            freshness = "fresh" if age <= 2 * config.refresh_minutes * 60 + 300 else "stale"
        return {
            "configured": state.configured, "host": status.host, "freshness": freshness, "last_success_at": status.last_success_at, "last_attempt_at": status.last_attempt_at,
            "age_seconds": age, "error": status.error, "consecutive_failures": status.consecutive_failures,
            "event_count": len(state.snapshot.facts) if state.snapshot else 0, "truncated": bool(state.snapshot and state.snapshot.truncated),
        }

    def _public(self, state: FeedState, now: datetime) -> dict:
        return self._brief(state, now) | {"config": state.config.model_dump(mode="json"), "overrides": dict(state.overrides)}

    async def status(self) -> dict:
        return self._public(await self._load(), self._clock())

    async def set_url(self, url: str) -> dict:
        """Checks the URL (scheme, port, resolved addresses) and stores it encrypted. The caller never gets it back."""
        async with self._lock:
            host = await self._fetcher.check(url)
            await self._store.set_url(url.strip(), host)
            self._invalidate()
        return await self.status()

    async def clear(self) -> dict:
        async with self._lock:
            await self._store.clear()
            self._invalidate()
        return await self.status()

    async def set_config(self, config: FeedConfig) -> dict:
        async with self._lock:
            await self._store.save_config(config)
            self._invalidate()
        return await self.status()

    async def set_override(self, key: str, classification: str | None) -> dict:
        """The owner's classification for one occurrence or a whole series (the key says which). None removes it."""
        if not key.startswith("ics:") or len(key) > 100:
            raise ValueError("unknown_event_key")
        async with self._lock:
            state = await self._load()
            overrides = dict(state.overrides)
            if classification is None:
                overrides.pop(key, None)
            else:
                EventClass(classification)  # ValueError for an unknown class
                if key not in overrides and len(overrides) >= MAX_OVERRIDES:
                    raise ValueError("too_many_overrides")
                overrides[key] = classification
            await self._store.save_overrides(overrides)
            self._invalidate()
        return await self.status()

    # --- refresh ---------------------------------------------------------------------------------------------------------------------------------------------

    async def refresh(self) -> dict:
        async with self._lock:
            state = await self._load()
            url = await self._store.get_url()
            now = self._clock()
            if url is None:
                return self._public(state, now)
            status = state.status.model_copy(update={"last_attempt_at": now})
            try:
                zone = await self._zone(state)
                fetched = await self._fetcher.fetch(url)
                rules = state.config.rules
                window_start = now - timedelta(days=2)
                window_end = now + timedelta(days=state.config.horizon_days)
                parsed = await asyncio.wait_for(
                    asyncio.to_thread(
                        parse_feed, fetched.body, window_start=window_start, window_end=window_end, tz=zone,
                        owner_emails=frozenset(a.lower() for a in rules.owner_emails),
                    ),
                    timeout=60,
                )
            except FeedError as exc:
                await self._store.save_status(status.model_copy(update={"error": exc.code, "consecutive_failures": status.consecutive_failures + 1}))
                self._invalidate()
                log.warning("calendar feed refresh failed: %s", exc.code)
                return await self.status()
            except Exception as exc:  # noqa: BLE001 - never put the message in a log: library errors can quote the URL or the feed
                await self._store.save_status(status.model_copy(update={"error": "internal_error", "consecutive_failures": status.consecutive_failures + 1}))
                self._invalidate()
                log.warning("calendar feed refresh failed: %s", type(exc).__name__)
                return await self.status()
            digest = hashlib.sha256("|".join(f"{f.key}:{f.revision}" for f in parsed.facts).encode()).hexdigest()[:16]
            snapshot = Snapshot(
                facts=parsed.facts, fetched_at=now, window_start=window_start, window_end=window_end, truncated=parsed.truncated, skipped=parsed.skipped, revision=digest,
            )
            await self._store.save_snapshot(snapshot, status.model_copy(update={"last_success_at": now, "error": None, "consecutive_failures": 0}))
            self._invalidate()
            log.info("calendar feed refreshed: %d occurrences, %d skipped", len(parsed.facts), parsed.skipped)
        return await self.status()

    async def refresh_if_due(self) -> bool:
        state = await self._load()
        if not state.configured:
            return False
        last = state.status.last_attempt_at
        if last is not None and self._clock() - last < timedelta(minutes=state.config.refresh_minutes):
            return False
        await self.refresh()
        return True

    # --- reading ---------------------------------------------------------------------------------------------------------------------------------------------

    def _classified(self, state: FeedState) -> list[tuple[EventFacts, Classification, str | None]]:
        if state.snapshot is None:
            return []
        rules = state.config.rules
        rows = []
        for facts in state.snapshot.facts:
            override = state.overrides.get(facts.key) or state.overrides.get(facts.series_key)
            rows.append((facts, apply_override(classify(facts, rules), override)))
        leave = [(f.start, f.end) for f, c in rows if c.event_class is EventClass.LEAVE_OR_OOO and f.status != "cancelled"]
        return [(f, c, reminder_decision(f, c, rules, leave)) for f, c in rows]

    async def events(self, start: datetime, end: datetime, *, include_cancelled: bool = False) -> list[CalendarEvent]:
        state = await self._load()
        out = []
        for facts, classification, blocked in self._classified(state):
            overlaps = facts.start < end and (facts.end > start or (facts.end == facts.start and facts.start >= start))
            if overlaps and (include_cancelled or facts.status != "cancelled"):
                out.append(display_event(facts, classification, blocked))
        return out

    async def reminders(self, now: datetime | None = None, hours: int | None = None) -> dict:
        """The bounded set of recording reminders the phone schedules locally. It replaces the phone's previous set; a reminder missing from it is cancelled there."""
        state = await self._load()
        now = now or self._clock()
        config = state.config
        hours = min(hours or config.device_horizon_hours, config.device_horizon_hours)
        horizon = now + timedelta(hours=hours)
        items = []
        for facts, classification, blocked in self._classified(state):
            if blocked is not None or facts.start <= now or facts.start > horizon:
                continue
            items.append({
                "event_key": facts.key, "series_key": facts.series_key, "revision": facts.revision,
                "title": None if facts.redacted or not facts.title else facts.title,
                "start": facts.start, "end": facts.end, "notify_at": facts.start - timedelta(minutes=config.lead_minutes),
                "lead_minutes": config.lead_minutes, "classification": classification.event_class.value, "basis": classification.basis.value,
                "recurring": facts.recurring,
            })
        items.sort(key=lambda item: (item["start"], item["event_key"]))
        return {
            "generated_at": now, "horizon_end": horizon, "lead_minutes": config.lead_minutes,
            "snapshot_revision": state.snapshot.revision if state.snapshot else None, "feed": self._brief(state, now),
            "reminders": items,
        }


class FeedCalendar:
    """A CalendarStore that adds the feed's events to another store's and classifies every event, whatever its source. Writes go to the inner store only."""

    def __init__(self, inner: CalendarStore, service: CalendarFeedService) -> None:
        self.inner, self.feed = inner, service

    async def add_event(self, event: CalendarEvent) -> CalendarEvent:
        return await self.inner.add_event(event)

    async def _others(self, events: list[CalendarEvent]) -> list[CalendarEvent]:
        state = await self.feed._load()
        out = []
        for event in events:
            if event.classification is None:
                facts = facts_from_event(event)
                classification = apply_override(classify(facts, state.config.rules), state.overrides.get(event.id))
                event = event.model_copy(update={
                    "classification": classification.event_class.value, "classification_basis": classification.basis.value, "classification_reasons": classification.reasons,
                })
            out.append(event)
        return out

    async def list_events(self, start: datetime, end: datetime, *, include_cancelled: bool = False) -> list[CalendarEvent]:
        others = await self._others(await self.inner.list_events(start, end))
        return sorted(others + await self.feed.events(start, end, include_cancelled=include_cancelled), key=lambda e: e.start)

    async def next_event(self, after: datetime) -> CalendarEvent | None:
        # "What's next" means the next thing at a time: a leave day or an all-day banner is not it.
        candidates = [e for e in await self.list_events(after, after + timedelta(days=31)) if e.start >= after and not e.all_day and e.classification != EventClass.LEAVE_OR_OOO.value]
        return min(candidates, key=lambda e: e.start, default=None)

    async def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if close is not None:
            await close()

    def __getattr__(self, name):
        return getattr(self.inner, name)


async def run_refresh_loop(service: CalendarFeedService, *, tick_seconds: float = 30.0) -> None:
    """Checks every `tick_seconds` whether a refresh is due (the interval is the owner's setting). A failed refresh waits a full interval like a good one."""
    while True:
        try:
            await service.refresh_if_due()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("calendar feed loop error: %s", type(exc).__name__)
        await asyncio.sleep(tick_seconds)
