"""Owner-only proxy for reviewing memory candidates (Phase 44F, docs/phase-44f-implementation-proposal.md).

Every route requires the logged-in OWNER SESSION (a cookie whose user is the owner): the REMOTE_UI_TOKEN bearer path is not accepted, because accepting a suggestion writes personal memory
and that token is a robot-control credential. Every change also requires the CSRF header. The hub validates a fixed body and forwards it; core decides everything else (what exists, what may be
accepted, what is saved) and the hub adds and removes nothing. Errors carry fixed messages, never candidate text. Nothing here is reachable by a spoken turn.
"""

from __future__ import annotations

import httpx
from fastapi import Depends, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from reachy_hub.operator import require_csrf
from shared.protocols.memory_candidates_api import (
    MEMORY_CANDIDATE_ACCEPT,
    MEMORY_CANDIDATE_REJECT,
    MEMORY_CANDIDATES,
    MEMORY_CANDIDATES_FORGET_CONVERSATION,
)

_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_ID = Path(pattern=r"^[A-Za-z0-9-]{1,64}$")


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=400)
    type: str | None = Field(default=None, pattern=r"^(profile|working|episodic)$")
    project_scope: str | None = Field(default=None, max_length=64)
    sensitivity: str | None = Field(default=None, pattern=r"^(public|work-private|sensitive)$")
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    acknowledge_lower: bool = False


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suppress: bool = False


class ForgetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1, max_length=200)


def install_memory_candidate_routes(app, require_owner_session, core) -> None:
    owner = [Depends(require_owner_session)]
    owner_change = [Depends(require_owner_session), Depends(require_csrf)]

    async def forward(call):
        try:
            return JSONResponse(await call(), headers=_NO_STORE)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (404, 409, 422):
                try:
                    detail = str(exc.response.json().get("detail", "Request refused"))[:200]
                except (ValueError, AttributeError):
                    detail = "Request refused"
                raise HTTPException(status, detail) from None
            raise HTTPException(502, "Memory suggestions unavailable") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Memory suggestions unavailable") from None

    @app.get(MEMORY_CANDIDATES, dependencies=owner)
    async def list_candidates():
        return await forward(core.list_memory_candidates)

    @app.post(MEMORY_CANDIDATES_FORGET_CONVERSATION, dependencies=owner_change)
    async def forget_conversation(body: ForgetBody):
        return await forward(lambda: core.forget_candidate_conversation(body.model_dump()))

    @app.post(MEMORY_CANDIDATE_ACCEPT, dependencies=owner_change)
    async def accept(body: AcceptBody, candidate_id: str = _ID):
        return await forward(lambda: core.accept_memory_candidate(candidate_id, body.model_dump(exclude_unset=True)))

    @app.post(MEMORY_CANDIDATE_REJECT, dependencies=owner_change)
    async def reject(body: RejectBody, candidate_id: str = _ID):
        return await forward(lambda: core.reject_memory_candidate(candidate_id, body.model_dump()))
