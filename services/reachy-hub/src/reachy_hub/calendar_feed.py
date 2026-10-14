"""Owner-only proxy for the read-only calendar feed (ADR 0035): the feed settings, the classified events and the recording reminders the phone schedules locally.

Every route requires the logged-in OWNER SESSION (the phone and the browser both sign in as the owner); the REMOTE_UI_TOKEN bearer path is not accepted, because the feed URL is
a credential and a robot-control token must not read or replace it. Every change also requires the CSRF header. The hub validates a fixed body and forwards it; core decides
everything else. Core's errors are mapped to fixed codes here, so nothing a client sent (the URL above all) can come back in an error body. No route returns the URL."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import unquote

import httpx
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from reachy_hub.operator import require_csrf
from shared.protocols.calendar_feed_api import (
    CORE_EVENTS,
    CORE_FEED,
    CORE_FEED_REFRESH,
    CORE_OVERRIDES,
    CORE_REMINDERS,
    CORE_SCHEDULE,
    HUB_EVENTS,
    HUB_FEED,
    HUB_FEED_REFRESH,
    HUB_OVERRIDES,
    HUB_REMINDERS,
    HUB_SCHEDULE,
    HUB_UPLOAD,
    MAX_UPLOAD_BYTES,
)

_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_CODE = re.compile(r"^[a-z0-9_]{1,40}$")


class FeedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, repr=False)  # length is checked in the route: a validation error would quote the input
    config: dict[str, Any] | None = None
    refresh: bool = True


class OverrideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=5, max_length=100)
    classification: str | None = Field(default=None, max_length=40)


def install_calendar_feed_routes(app, require_owner_session, core) -> None:
    owner = [Depends(require_owner_session)]
    owner_change = [Depends(require_owner_session), Depends(require_csrf)]

    async def forward(call):
        try:
            return JSONResponse(await call(), headers=_NO_STORE)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 400:  # a fixed code from core (unsafe_url, unsafe_address, ...)
                try:
                    detail = str(exc.response.json().get("detail", ""))
                except (ValueError, AttributeError):
                    detail = ""
                raise HTTPException(400, detail if _CODE.match(detail) else "request_refused") from None
            if status in (422, 503):  # never core's validation text: it quotes the input
                raise HTTPException(status, "invalid_request" if status == 422 else "calendar_feed_unavailable") from None
            raise HTTPException(502, "calendar_feed_unavailable") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "calendar_feed_unavailable") from None

    @app.get(HUB_FEED, dependencies=owner)
    async def feed_status():
        return await forward(lambda: core.planner_request("GET", CORE_FEED))

    @app.put(HUB_FEED, dependencies=owner_change)
    async def feed_update(body: FeedBody):
        if body.url is not None and len(body.url) > 2048:
            raise HTTPException(422, "invalid_request")
        return await forward(lambda: core.planner_request("PUT", CORE_FEED, json=body.model_dump(exclude_unset=True), timeout=90.0))

    @app.delete(HUB_FEED, dependencies=owner_change)
    async def feed_clear():
        return await forward(lambda: core.planner_request("DELETE", CORE_FEED))

    @app.post(HUB_FEED_REFRESH, dependencies=owner_change)
    async def feed_refresh():
        return await forward(lambda: core.planner_request("POST", CORE_FEED_REFRESH, timeout=90.0))

    @app.put(HUB_OVERRIDES, dependencies=owner_change)
    async def override_set(body: OverrideBody):
        return await forward(lambda: core.planner_request("PUT", CORE_OVERRIDES, json=body.model_dump()))

    @app.delete(HUB_OVERRIDES, dependencies=owner_change)
    async def override_clear(body: OverrideBody):
        return await forward(lambda: core.planner_request("DELETE", CORE_OVERRIDES, json=body.model_dump()))

    @app.get(HUB_REMINDERS, dependencies=owner)
    async def reminders(hours: int | None = Query(default=None, ge=1, le=168)):
        return await forward(lambda: core.planner_request("GET", CORE_REMINDERS, params={"hours": str(hours)} if hours else None))

    @app.put(HUB_UPLOAD, dependencies=owner_change)
    async def feed_upload(request: Request):
        """The owner's ICS file, validated whole by core and published as one new revision. The file is never logged and never echoed."""
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "too_large")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_UPLOAD_BYTES:
                raise HTTPException(400, "too_large")
        filename = unquote(request.headers.get("x-filename", "")) or None
        return await forward(lambda: core.calendar_upload(bytes(body), filename))

    @app.get(HUB_SCHEDULE, dependencies=owner)
    async def schedule(start: datetime, end: datetime, include_cancelled: bool = False):
        return await forward(lambda: core.planner_request(
            "GET", CORE_SCHEDULE, params={"start": start.isoformat(), "end": end.isoformat(), "include_cancelled": str(include_cancelled).lower()}))

    @app.get(HUB_EVENTS, dependencies=owner)
    async def events(start: datetime, end: datetime, include_cancelled: bool = False):
        return await forward(lambda: core.planner_request(
            "GET", CORE_EVENTS, params={"start": start.isoformat(), "end": end.isoformat(), "include_cancelled": str(include_cancelled).lower()}))
