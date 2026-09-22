"""companion-core: reasoning/tools/memory service.

Phase 4: minimal service proving companion-core -> reachy-hub ->
reachy-embodiment end to end. The `/debug/*` routes are a stand-in for what
will eventually be an agent tool call — not the tool-calling framework
itself.

Phase 5: POST /conversation is the real, stable contract reachy-hub calls
per turn (ADR 0002) — companion-core receives only a session_id,
conversation_id, channel label, and text, never "this came from Telegram"
as anything but an opaque string. The reasoning inside is a placeholder
(echoes turn count) until Phase 10+ replaces it with a real agent.

Phase 9: the response now carries real (if simplistic) `Privacy`/`Urgency`
metadata (privacy_classifier.py) — companion-core *proposes* this per
docs/plan.md §4 ("the LLM may propose metadata"); reachy-hub's response
router (Phase 9, ADR 0006) has final, enforced authority over what actually
happens with it.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from companion_core.conversation import ConversationStore
from companion_core.hub_client import HubClient
from companion_core.privacy_classifier import classify_privacy
from shared.models.response import Privacy


class ConversationTurnRequest(BaseModel):
    session_id: str
    conversation_id: str
    channel: str
    text: str


class ConversationTurnResponse(BaseModel):
    reply: str
    turn_count: int
    privacy: Privacy


def create_app(*, hub_base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    hub_base_url = hub_base_url or os.environ.get("REACHY_HUB_URL", "http://reachy-hub:8000")
    conversation_store = ConversationStore()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.hub_client = HubClient(hub_base_url, transport=transport)
        try:
            yield
        finally:
            await app.state.hub_client.aclose()

    app = FastAPI(title="companion-core", lifespan=lifespan)
    app.state.conversation_store = conversation_store

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/conversation")
    async def conversation_turn(turn: ConversationTurnRequest) -> ConversationTurnResponse:
        history = conversation_store.append(turn.session_id, turn.channel, turn.text)
        reply = f"(turn {len(history)} via {turn.channel}) heard: {turn.text}"
        return ConversationTurnResponse(reply=reply, turn_count=len(history), privacy=classify_privacy(turn.text))

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
