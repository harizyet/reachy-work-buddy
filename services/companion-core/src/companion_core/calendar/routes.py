"""Core routes for the read-only calendar feed (ADR 0035). They sit behind the service token like every other core route; the hub proxies them for the owner session only.

Errors carry a fixed code and never the URL or anything the feed said. Nothing here modifies a calendar: the only writes are the owner's own settings, overrides and the
stored URL.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from companion_core.calendar.classify import EventClass
from companion_core.calendar.feed import CalendarFeedService, FeedCalendar, FeedConfig
from companion_core.calendar.ics import FeedError
from companion_core.calendar.models import CalendarEvent
from shared.protocols.calendar_feed_api import (
    CORE_EVENTS,
    CORE_FEED,
    CORE_FEED_REFRESH,
    CORE_OVERRIDES,
    CORE_REMINDERS,
)


class FeedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, max_length=2048, repr=False)  # repr=False: the URL is a secret, keep it out of any accidental log of the model
    config: FeedConfig | None = None
    refresh: bool = True  # download once straight away after a new URL, so the owner sees whether it works


class OverrideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=5, max_length=100)
    classification: str | None = None


def occupying(event: CalendarEvent) -> bool:
    """Whether the event means the owner is busy at that time: timed, not cancelled, not declined, not shown as free, not a leave day or an all-day banner."""
    return (
        event.busy and not event.all_day and event.status != "cancelled" and event.response != "declined"
        and event.classification != EventClass.LEAVE_OR_OOO.value
    )


def install_calendar_routes(app: FastAPI) -> None:
    def service() -> CalendarFeedService:
        svc = getattr(app.state, "calendar_feed", None)
        if svc is None:
            raise HTTPException(503, "calendar_feed_unavailable")
        return svc

    @app.get(CORE_FEED)
    async def feed_status() -> dict:
        return await service().status()

    @app.put(CORE_FEED)
    async def feed_update(body: FeedUpdate) -> dict:
        svc = service()
        try:
            if body.config is not None:
                await svc.set_config(body.config)
            if body.url is not None:
                await svc.set_url(body.url)
                if body.refresh:
                    return await svc.refresh()
            return await svc.status()
        except FeedError as exc:
            raise HTTPException(400, exc.code) from None

    @app.delete(CORE_FEED)
    async def feed_clear() -> dict:
        return await service().clear()

    @app.post(CORE_FEED_REFRESH)
    async def feed_refresh() -> dict:
        return await service().refresh()

    @app.put(CORE_OVERRIDES)
    async def override_set(body: OverrideBody) -> dict:
        if body.classification is None:
            raise HTTPException(422, "classification_required")
        try:
            return await service().set_override(body.key, body.classification)
        except ValueError as exc:
            raise HTTPException(422, str(exc) if str(exc) in {"unknown_event_key", "too_many_overrides"} else "unknown_classification") from None

    @app.delete(CORE_OVERRIDES)
    async def override_clear(body: OverrideBody) -> dict:
        try:
            return await service().set_override(body.key, None)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get(CORE_REMINDERS)
    async def meeting_reminders(hours: int | None = Query(default=None, ge=1, le=168)) -> dict:
        return await service().reminders(hours=hours)

    @app.get(CORE_EVENTS)
    async def list_events(start: datetime, end: datetime, include_cancelled: bool = False, only_occupying: bool = Query(default=False, alias="occupying")) -> list[CalendarEvent]:
        store = app.state.calendar_store
        if isinstance(store, FeedCalendar):
            events = await store.list_events(start, end, include_cancelled=include_cancelled)
        else:
            events = await store.list_events(start, end)
        return [event for event in events if occupying(event)] if only_occupying else events
