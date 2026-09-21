"""companion-core: reasoning/tools/memory service.

Phase 4 scope only. Real reasoning, tool-calling, memory, and RAG are later
phases (10-14); this is the minimal service needed to prove Phase 4's exit
criterion end to end: companion-core -> reachy-hub -> reachy-embodiment. The
`/debug/*` routes below are a stand-in for what will eventually be an agent
tool call — they are not the tool-calling framework itself.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException

from companion_core.hub_client import HubClient


def create_app(*, hub_base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    hub_base_url = hub_base_url or os.environ.get("REACHY_HUB_URL", "http://reachy-hub:8000")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.hub_client = HubClient(hub_base_url, transport=transport)
        try:
            yield
        finally:
            await app.state.hub_client.aclose()

    app = FastAPI(title="companion-core", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/debug/robots/{robot_id}/state")
    async def debug_robot_state(robot_id: str) -> dict:
        try:
            return await app.state.hub_client.get_robot_state(robot_id)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"reachy-hub unreachable: {exc}") from exc

    @app.post("/debug/robots/{robot_id}/behaviour/{name}")
    async def debug_trigger_behaviour(robot_id: str, name: str) -> dict:
        try:
            return await app.state.hub_client.trigger_behaviour(robot_id, name)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"reachy-hub unreachable: {exc}") from exc

    return app
