"""Owner-only, read-only proxy for the Brain view (Phase 47D, docs/phase-47.md section 7).

The hub authenticates the owner's session and forwards a fixed, validated set of parameters. It sends nothing that could
widen what core reveals (no sensitivity, principal or destination), because core decides what the owner may see from its own
trusted state. A record core withholds is simply absent; the hub adds nothing and removes nothing. Bearer tokens are not
accepted: this is a full view of personal records and `REMOTE_UI_TOKEN` is a robot-control credential.
"""

from __future__ import annotations

import httpx
from fastapi import Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse

from shared.protocols.brain_api import (
    BRAIN_EDGES,
    BRAIN_NODE,
    BRAIN_NODES,
    BRAIN_SUMMARY,
)

_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_TYPES = r"^(memory|document|meeting|note|task|reminder)(,(memory|document|meeting|note|task|reminder)){0,5}$"


def install_brain_routes(app, require_owner_session, core) -> None:
    owner = [Depends(require_owner_session)]

    async def forward(call):
        try:
            return JSONResponse(await call(), headers=_NO_STORE)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (404, 422):
                detail = "Record not found" if status == 404 else "Invalid request"
                raise HTTPException(status, detail) from None
            raise HTTPException(502, "Knowledge view unavailable") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Knowledge view unavailable") from None

    @app.get(BRAIN_SUMMARY, dependencies=owner)
    async def brain_summary():
        return await forward(core.get_brain_summary)

    @app.get(BRAIN_NODES, dependencies=owner)
    async def brain_nodes(
        types: str | None = Query(default=None, pattern=_TYPES),
        q: str = Query(default="", max_length=200),
        limit: int = Query(default=100, ge=1, le=200),
        cursor: str | None = Query(default=None, max_length=512, pattern=r"^[A-Za-z0-9_-]*$"),
    ):
        return await forward(lambda: core.list_brain_nodes(types=types, q=q, limit=limit, cursor=cursor))

    @app.get(BRAIN_NODE, dependencies=owner)
    async def brain_node(
        source_type: str = Path(pattern=r"^[a-z]{1,16}$"),
        source_id: str = Path(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._-]+$"),
    ):
        return await forward(lambda: core.get_brain_node(source_type, source_id))

    @app.get(BRAIN_EDGES, dependencies=owner)
    async def brain_edges(ids: str = Query(default="", max_length=20000, pattern=r"^[A-Za-z0-9._:,-]*$")):
        return await forward(lambda: core.get_brain_edges(ids))
