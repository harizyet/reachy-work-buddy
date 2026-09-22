"""Authenticated operator API. Reasoning settings remain owned by core."""

import asyncio

import httpx
from fastapi import Depends, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shared.models.llm import LLMConfigPatch
from shared.protocols.operator_api import (
    AUTH_LOGIN,
    AUTH_LOGOUT,
    AUTH_ME,
    LLM_SETTINGS,
    LLM_USAGE,
    STATUS,
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=4096, repr=False)


def require_csrf(request: Request) -> None:
    # A custom header requires a CORS preflight; this app grants no cross-origin
    # access. This also protects login against cross-site session swapping.
    if request.headers.get("X-Reachy-CSRF") != "1":
        raise HTTPException(403, "Missing same-origin request header")


def install_operator_routes(
    app, require_auth, core, get_robot_client, *, login_enabled, telegram_enabled
):

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(request, exc):
        if request.url.path in (LLM_SETTINGS, AUTH_LOGIN):
            return JSONResponse(
                status_code=422, content={"detail": "Invalid request fields"}
            )
        return await request_validation_exception_handler(request, exc)

    dependencies = [Depends(require_auth)]

    @app.post(AUTH_LOGIN, dependencies=[Depends(require_csrf)])
    async def login(body: LoginRequest, request: Request) -> dict:
        if not login_enabled or await app.state.user_store.owner() is None:
            raise HTTPException(503, "Owner login is not configured")
        if not await app.state.user_store.authenticate(body.username, body.password):
            raise HTTPException(401, "Invalid username or password")
        request.session.clear()
        request.session["user"] = body.username
        return {"username": body.username}

    @app.post(AUTH_LOGOUT, dependencies=[Depends(require_csrf)])
    async def logout(request: Request) -> dict:
        if login_enabled:
            request.session.clear()
        return {"ok": True}

    @app.get(AUTH_ME)
    async def me(request: Request) -> dict:
        user = request.scope.get("session", {}).get("user")
        if not login_enabled or not user or user != await app.state.user_store.owner():
            raise HTTPException(401, "Login required")
        return {"username": user}

    async def proxy(method, *args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 422:
                raise HTTPException(422, "Invalid provider settings") from None
            raise HTTPException(502, "Companion core request failed") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Companion core unavailable") from None

    @app.get(LLM_SETTINGS, dependencies=dependencies)
    async def get_settings() -> dict:
        return await proxy(core.get_llm_settings)

    @app.put(LLM_SETTINGS, dependencies=dependencies)
    async def put_settings(patch: LLMConfigPatch) -> dict:
        return await proxy(
            core.set_llm_settings, patch.model_dump(mode="json", exclude_unset=True)
        )

    @app.get(LLM_USAGE, dependencies=dependencies)
    async def usage(
        limit: int = Query(50, ge=1, le=500),
        since_hours: int = Query(24, ge=1, le=8760),
    ) -> dict:
        return await proxy(core.get_llm_usage, limit=limit, since_hours=since_hours)

    @app.get(STATUS, dependencies=dependencies)
    async def status() -> dict:
        async def probe(call):
            try:
                return {"status": "ok", "data": await call()}
            except (httpx.HTTPError, ValueError):
                return {"status": "unavailable"}

        robots = await app.state.registry.list()
        results = await asyncio.gather(
            probe(core.health),
            probe(core.get_llm_settings),
            probe(core.get_llm_usage),
            *(probe(get_robot_client(robot).get_state) for robot in robots),
        )
        health, settings, usage_result, *robot_results = results
        return {
            "reachy_hub": {"status": "ok"},
            "companion_core": health,
            "robots": [
                {"robot_id": robot.robot_id, **result}
                for robot, result in zip(robots, robot_results)
            ],
            "llm": {
                "status": settings["status"],
                "configured": bool(settings.get("data", {}).get("local"))
                if settings["status"] == "ok"
                else None,
                "usage": usage_result,
            },
            # This is configuration, not poll-loop health (Phase 20).
            "telegram": {"configured": telegram_enabled},
        }
