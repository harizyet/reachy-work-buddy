"""HTTP surface of the model manager. Manual operation only: no routing, escalation or scheduling lives here.
Bound to loopback and token-protected: whoever can call it can take the local model offline for minutes."""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from model_manager.machine import (
    Busy,
    JobFailed,
    ModelManager,
    NotAllowed,
    RestoreFailed,
    TierSwitchFailed,
)
from shared.models.model_manager import ManagerStatus, ModelTier, TransitionRecord
from shared.protocols.model_manager_api import (
    MANAGER_ACTIVATE,
    MANAGER_HEALTH,
    MANAGER_METRICS,
    MANAGER_RESTORE,
    MANAGER_STATE,
    MANAGER_TRANSITIONS,
)


class ActivateRequest(BaseModel):
    tier: ModelTier
    lease_seconds: float | None = Field(default=None, gt=0)


def create_app(manager: ModelManager, token: str, *, reconcile_on_start: bool = True) -> FastAPI:
    import asyncio

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.ensure_future(manager.start()) if reconcile_on_start else None
        try:
            yield
        finally:
            if task and not task.done():
                task.cancel()
            await manager.close()

    app = FastAPI(title="reachy model manager", lifespan=lifespan)

    def require_token(authorization: str | None = Header(default=None)) -> None:
        supplied = (authorization or "").removeprefix("Bearer ")
        if not authorization or not secrets.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(401, "Invalid or missing bearer token")

    def status() -> ManagerStatus:
        try:
            return manager.status()
        except NotAllowed as exc:
            raise HTTPException(503, str(exc)) from None

    async def guarded(call):
        try:
            return await call
        except Busy as exc:
            raise HTTPException(409, str(exc)) from None
        except NotAllowed as exc:
            raise HTTPException(409, str(exc)) from None
        except TierSwitchFailed as exc:
            raise HTTPException(502, {"error": str(exc), "fast_tier_restored": exc.restored}) from None
        except RestoreFailed as exc:
            raise HTTPException(503, {"error": str(exc), "state": "failed"}) from None

    @app.get(MANAGER_HEALTH)
    async def health() -> dict:
        return {"status": "ok"}

    @app.get(MANAGER_STATE, dependencies=[Depends(require_token)])
    async def get_state() -> ManagerStatus:
        return status()

    @app.post(MANAGER_ACTIVATE, dependencies=[Depends(require_token)])
    async def activate(request: ActivateRequest) -> ManagerStatus:
        return await guarded(manager.activate(request.tier, request.lease_seconds))

    @app.post(MANAGER_RESTORE, dependencies=[Depends(require_token)])
    async def restore() -> ManagerStatus:
        return await guarded(manager.restore())

    @app.get(MANAGER_TRANSITIONS, dependencies=[Depends(require_token)])
    async def transitions(limit: int = Query(default=50, ge=1, le=500)) -> list[TransitionRecord]:
        return manager.transitions(limit)

    @app.get(MANAGER_METRICS, dependencies=[Depends(require_token)])
    async def metrics() -> dict:
        return manager.counters

    return app


__all__ = ["JobFailed", "create_app"]
