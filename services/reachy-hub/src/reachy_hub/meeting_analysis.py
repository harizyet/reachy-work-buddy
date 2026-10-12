"""Owner-only proxy for meeting analysis (Phase 31, docs/phase-31.md): analysis status, the review of action candidates and the provenance of a confirmed task.

Every route requires the logged-in OWNER SESSION (a cookie whose user is the owner): the REMOTE_UI_TOKEN bearer path is not accepted, because confirming an action creates a task and
that token is a robot-control credential. Every change also requires the CSRF header. The hub validates a fixed body and forwards it; core decides everything else and the hub adds and
removes nothing. Errors carry fixed messages, never transcript or item text. When core has the feature off, the config route answers {"enabled": false} and the others answer 404."""

from __future__ import annotations

from urllib.parse import quote

import httpx
from fastapi import Depends, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from reachy_hub.operator import require_csrf
from shared.protocols.meeting_analysis_api import (
    MEETING_ANALYSIS,
    MEETING_ANALYSIS_ACCEPT,
    MEETING_ANALYSIS_CONFIG,
    MEETING_ANALYSIS_DISMISS,
    MEETING_ANALYSIS_ITEMS,
    MEETING_ANALYSIS_PROVENANCE,
    MEETING_ANALYSIS_RETRY,
)

_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_ID = r"^[A-Za-z0-9_-]{1,64}$"


class EnqueueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=300)


def install_meeting_analysis_routes(app, require_owner_session, core) -> None:
    owner = [Depends(require_owner_session)]
    owner_change = [Depends(require_owner_session), Depends(require_csrf)]

    async def forward(call):
        try:
            return JSONResponse(await call(), headers=_NO_STORE)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (404, 409, 422, 503):
                try:
                    detail = str(exc.response.json().get("detail", "Request refused"))[:200]
                except (ValueError, AttributeError):
                    detail = "Request refused"
                raise HTTPException(status, detail) from None
            raise HTTPException(502, "Meeting analysis unavailable") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Meeting analysis unavailable") from None

    @app.get(MEETING_ANALYSIS_CONFIG, dependencies=owner)
    async def config():
        try:
            return JSONResponse(await core.planner_request("GET", MEETING_ANALYSIS_CONFIG), headers=_NO_STORE)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:  # core does not have the feature on
                return JSONResponse({"enabled": False}, headers=_NO_STORE)
            raise HTTPException(502, "Meeting analysis unavailable") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Meeting analysis unavailable") from None

    @app.get(MEETING_ANALYSIS, dependencies=owner)
    async def status(meeting_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("GET", f"/meetings/{quote(meeting_id, safe='')}/analysis"))

    @app.post(MEETING_ANALYSIS, dependencies=owner_change)
    async def enqueue(body: EnqueueBody, meeting_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("POST", f"/meetings/{quote(meeting_id, safe='')}/analysis", json=body.model_dump(), timeout=30.0))

    @app.post(MEETING_ANALYSIS_RETRY, dependencies=owner_change)
    async def retry(run_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("POST", f"/meeting-analysis/runs/{quote(run_id, safe='')}/retry"))

    @app.get(MEETING_ANALYSIS_ITEMS, dependencies=owner)
    async def items():
        return await forward(lambda: core.planner_request("GET", MEETING_ANALYSIS_ITEMS))

    @app.post(MEETING_ANALYSIS_ACCEPT, dependencies=owner_change)
    async def accept(body: AcceptBody, item_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("POST", f"/meeting-analysis/items/{quote(item_id, safe='')}/accept", json=body.model_dump(exclude_unset=True), timeout=20.0))

    @app.post(MEETING_ANALYSIS_DISMISS, dependencies=owner_change)
    async def dismiss(item_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("POST", f"/meeting-analysis/items/{quote(item_id, safe='')}/dismiss"))

    @app.get(MEETING_ANALYSIS_PROVENANCE, dependencies=owner)
    async def provenance(record_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("GET", f"/meeting-analysis/provenance/{quote(record_id, safe='')}"))
