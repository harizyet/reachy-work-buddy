"""Owner-only proxy for the Home dashboard (docs/phase-51.md): the structured snapshot and "Brief me on today".

Every route requires the logged-in OWNER SESSION (a cookie whose user is the owner); the REMOTE_UI_TOKEN bearer path is not accepted, because the snapshot summarises private records and
that token is a robot-control credential. The brief is a POST (it may run the local model), so it also requires the CSRF header. Both are read-only. The hub sends no access ceiling, so
core reads at its default, work-private: sensitive records never appear on a dashboard. Responses are not cached by browsers or proxies. Errors carry fixed messages, never record text.
"""

from __future__ import annotations

import httpx
from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from reachy_hub.operator import require_csrf
from shared.protocols.home_api import HOME, HOME_BRIEF

_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


class BriefBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narrative: bool = True


def install_home_routes(app, require_owner_session, core) -> None:
    owner = [Depends(require_owner_session)]
    owner_change = [Depends(require_owner_session), Depends(require_csrf)]

    async def forward(call):
        try:
            return JSONResponse(await call(), headers=_NO_STORE)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 422:
                raise HTTPException(422, "Unknown section") from None
            raise HTTPException(502, "Home unavailable") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Home unavailable") from None

    @app.get(HOME, dependencies=owner)
    async def home(sections: str | None = Query(default=None, max_length=100, pattern=r"^[a-z,]*$")):
        return await forward(lambda: core.planner_request("GET", HOME, params={"sections": sections} if sections else None, timeout=20.0))

    @app.post(HOME_BRIEF, dependencies=owner_change)
    async def brief(body: BriefBody):
        return await forward(lambda: core.planner_request("POST", HOME_BRIEF, json=body.model_dump(), timeout=90.0))  # a local-model rewording can take a while; the lines never wait on it elsewhere
