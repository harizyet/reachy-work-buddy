"""Authenticated operator API. Reasoning settings remain owned by core."""

import asyncio
from datetime import datetime
from urllib.parse import quote

import httpx
from fastapi import Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shared.models.llm import LLMConfigPatch
from shared.models.persona import PersonaPatch
from shared.models.websearch import SearchConfigPatch
from shared.protocols.operator_api import (
    AUTH_LOGIN,
    AUTH_LOGOUT,
    AUTH_ME,
    LLM_SETTINGS,
    LLM_USAGE,
    MEETING,
    MEETING_CANCEL,
    MEETINGS,
    PERSONA_SETTINGS,
    PLANNER_NOTE,
    PLANNER_NOTES,
    PLANNER_REMINDER,
    PLANNER_REMINDER_COMPLETE,
    PLANNER_REMINDERS,
    PLANNER_TASK,
    PLANNER_TASK_COMPLETE,
    PLANNER_TASK_REOPEN,
    PLANNER_TASKS,
    STATUS,
    WEBSEARCH_LOG,
    WEBSEARCH_SETTINGS,
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=4096, repr=False)


class PlannerTextBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class PlannerNoteBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=20000)


class PlannerReminderBody(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    due_at: datetime


def require_csrf(request: Request) -> None:
    # A custom header requires a CORS preflight; this app grants no cross-origin
    # access. This also protects login against cross-site session swapping.
    if request.headers.get("X-Reachy-CSRF") != "1":
        raise HTTPException(403, "Missing same-origin request header")


def install_operator_routes(
    app, require_auth, core, get_robot_client, *, login_enabled, telegram_enabled, default_user_id,
    owner_bound=False, on_logout=None
):

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(request, exc):
        if request.url.path in (LLM_SETTINGS, WEBSEARCH_SETTINGS, AUTH_LOGIN) or request.url.path.startswith("/settings/accounts/"):
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
        # Phase 24c: an owner-started robot microphone session must not
        # outlive the login that started it.
        if on_logout is not None:
            await on_logout()
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

    @app.get(PERSONA_SETTINGS, dependencies=dependencies)
    async def get_persona() -> dict:
        return await proxy(core.get_persona)

    @app.put(PERSONA_SETTINGS, dependencies=dependencies)
    async def put_persona(patch: PersonaPatch) -> dict:
        return await proxy(core.set_persona, patch.model_dump(mode="json", exclude_unset=True))

    @app.get(WEBSEARCH_SETTINGS, dependencies=dependencies)
    async def get_websearch_settings() -> dict:
        return await proxy(core.get_websearch_settings)

    @app.put(WEBSEARCH_SETTINGS, dependencies=dependencies)
    async def put_websearch_settings(patch: SearchConfigPatch) -> dict:
        return await proxy(
            core.set_websearch_settings, patch.model_dump(mode="json", exclude_unset=True)
        )

    @app.get(WEBSEARCH_LOG, dependencies=dependencies)
    async def get_websearch_log() -> dict:
        return await proxy(core.get_websearch_log)

    @app.get(LLM_USAGE, dependencies=dependencies)
    async def usage(
        limit: int = Query(50, ge=1, le=500),
        since_hours: int = Query(24, ge=1, le=8760),
    ) -> dict:
        return await proxy(core.get_llm_usage, limit=limit, since_hours=since_hours)

    def meeting_error(exc: httpx.HTTPStatusError):
        # 27.1: companion-core's own 404/409/422 are meaningful to the
        # owner (no such meeting, past the cancellable stage, bad upload) —
        # pass those through rather than collapsing them into 502 like the
        # generic `proxy()` helper above does for settings routes.
        if exc.response.status_code in (404, 409, 422):
            raise HTTPException(exc.response.status_code, exc.response.json().get("detail", "Request rejected")) from None
        raise HTTPException(502, "Companion core request failed") from None

    @app.post(MEETINGS, dependencies=dependencies)
    async def upload_meeting(
        title: str = Form(...),
        project_scope: str | None = Form(None),
        context: str | None = Form(None),
        participants: str = Form(""),
        started_at: str | None = Form(None),
        audio: UploadFile = File(...),  # noqa: B008
    ) -> dict:
        try:
            return await core.create_meeting(
                title=title,
                audio_bytes=audio.file,
                filename=audio.filename or "recording",
                content_type=audio.content_type or "application/octet-stream",
                project_scope=project_scope,
                context=context,
                participants=participants,
                started_at=started_at,
            )
        except httpx.HTTPStatusError as exc:
            meeting_error(exc)
        except httpx.HTTPError:
            raise HTTPException(502, "Companion core unavailable") from None

    @app.get(MEETINGS, dependencies=dependencies)
    async def list_meetings() -> list[dict]:
        try:
            return await core.list_meetings()
        except httpx.HTTPError:
            raise HTTPException(502, "Companion core unavailable") from None

    @app.get(MEETING, dependencies=dependencies)
    async def get_meeting(meeting_id: str) -> dict:
        try:
            return await core.get_meeting(meeting_id)
        except httpx.HTTPStatusError as exc:
            meeting_error(exc)
        except httpx.HTTPError:
            raise HTTPException(502, "Companion core unavailable") from None

    @app.post(MEETING_CANCEL, dependencies=dependencies)
    async def cancel_meeting(meeting_id: str) -> dict:
        try:
            return await core.cancel_meeting(meeting_id)
        except httpx.HTTPStatusError as exc:
            meeting_error(exc)
        except httpx.HTTPError:
            raise HTTPException(502, "Companion core unavailable") from None

    async def planner(method: str, path: str, *, json=None, params=None):
        # Core's 404/422 name the missing or invalid item; pass them through.
        try:
            return await core.planner_request(method, path, json=json, params=params)
        except httpx.HTTPStatusError as exc:
            meeting_error(exc)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Companion core unavailable") from None

    @app.get(PLANNER_TASKS, dependencies=dependencies)
    async def planner_list_tasks(status: str | None = Query(None, pattern="^(open|done)$")) -> list[dict]:
        return await planner("GET", "/tasks", params={"status": status} if status else None)

    @app.post(PLANNER_TASKS, dependencies=dependencies)
    async def planner_add_task(body: PlannerTextBody) -> dict:
        return await planner("POST", "/tasks", json={"text": body.text})

    @app.put(PLANNER_TASK, dependencies=dependencies)
    async def planner_edit_task(item_id: str, body: PlannerTextBody) -> dict:
        return await planner("PUT", f"/tasks/{quote(item_id, safe='')}", json={"text": body.text})

    @app.delete(PLANNER_TASK, dependencies=dependencies)
    async def planner_delete_task(item_id: str) -> dict:
        return await planner("DELETE", f"/tasks/{quote(item_id, safe='')}")

    @app.post(PLANNER_TASK_COMPLETE, dependencies=dependencies)
    async def planner_complete_task(item_id: str) -> dict:
        return await planner("POST", f"/tasks/{quote(item_id, safe='')}/complete")

    @app.post(PLANNER_TASK_REOPEN, dependencies=dependencies)
    async def planner_reopen_task(item_id: str) -> dict:
        return await planner("POST", f"/tasks/{quote(item_id, safe='')}/reopen")

    @app.get(PLANNER_NOTES, dependencies=dependencies)
    async def planner_list_notes(q: str | None = Query(None, max_length=200)) -> list[dict]:
        return await planner("GET", "/notes", params={"q": q} if q else None)

    @app.post(PLANNER_NOTES, dependencies=dependencies)
    async def planner_add_note(body: PlannerNoteBody) -> dict:
        return await planner("POST", "/notes", json=body.model_dump())

    @app.put(PLANNER_NOTE, dependencies=dependencies)
    async def planner_edit_note(item_id: str, body: PlannerNoteBody) -> dict:
        return await planner("PUT", f"/notes/{quote(item_id, safe='')}", json=body.model_dump())

    @app.delete(PLANNER_NOTE, dependencies=dependencies)
    async def planner_delete_note(item_id: str) -> dict:
        return await planner("DELETE", f"/notes/{quote(item_id, safe='')}")

    @app.get(PLANNER_REMINDERS, dependencies=dependencies)
    async def planner_list_reminders() -> list[dict]:
        return await planner("GET", "/reminders")

    @app.post(PLANNER_REMINDERS, dependencies=dependencies)
    async def planner_add_reminder(body: PlannerReminderBody) -> dict:
        return await planner("POST", "/reminders", json=body.model_dump(mode="json"))

    @app.post(PLANNER_REMINDER_COMPLETE, dependencies=dependencies)
    async def planner_complete_reminder(item_id: str) -> dict:
        return await planner("POST", f"/reminders/{quote(item_id, safe='')}/complete")

    @app.delete(PLANNER_REMINDER, dependencies=dependencies)
    async def planner_delete_reminder(item_id: str) -> dict:
        return await planner("DELETE", f"/reminders/{quote(item_id, safe='')}")

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
                "configured": bool(settings.get("data", {}).get("local") or settings.get("data", {}).get("cloud"))
                if settings["status"] == "ok"
                else None,
                "usage": usage_result,
            },
            "telegram": app.state.telegram_poll_health.snapshot(configured=telegram_enabled),
            "default_user_id": default_user_id,
            "owner_bound": owner_bound,
        }
