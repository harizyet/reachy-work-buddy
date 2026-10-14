"""Owner-only proxy for the supervised meeting-minutes email (Phase 55, ADR 0039).

Every route requires the logged-in OWNER SESSION (a cookie whose user is the owner). The REMOTE_UI_TOKEN bearer is NOT accepted: it is a robot-control credential and these routes can
approve an outbound message. Every change also requires the CSRF header. The hub validates a fixed body and forwards it; core decides everything else (the typed confirmation, the package hash,
the sender, the state machine) and the hub adds and removes nothing. Nothing here can be reached from a voice or chat turn. When core has the feature off, the config route answers
{"enabled": false} and the others answer 404. The sender credential is write-only: no response from core contains it."""

from __future__ import annotations

from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import Depends, HTTPException, Path, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from reachy_hub.operator import require_csrf
from shared.protocols import meeting_email_api as api

_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_ID = r"^[A-Za-z0-9_-]{1,64}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SenderBody(Strict):
    host: str = Field(max_length=253)
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["starttls", "none"] = "starttls"
    from_address: str = Field(max_length=254)
    username: str = Field(default="", max_length=254)
    password: str | None = Field(default=None, max_length=256, repr=False)
    clear_password: bool = False


class EnabledBody(Strict):
    enabled: bool


class SenderTestBody(Strict):
    to: str = Field(max_length=254)


class GroupBody(Strict):
    name: str = Field(max_length=80)
    addresses: list[str] = Field(max_length=20)


class PrepareBody(Strict):
    allow_sensitive: bool = False
    include_pdf: bool = True
    to: list[str] = Field(default_factory=list, max_length=20)
    cc: list[str] = Field(default_factory=list, max_length=20)
    bcc: list[str] = Field(default_factory=list, max_length=20)
    group_ids: list[str] = Field(default_factory=list, max_length=10)


class EditBody(Strict):
    to: list[str] | None = Field(default=None, max_length=20)
    cc: list[str] | None = Field(default=None, max_length=20)
    bcc: list[str] | None = Field(default=None, max_length=20)
    group_ids: list[str] | None = Field(default=None, max_length=10)
    subject: str | None = Field(default=None, max_length=400)
    body: str | None = Field(default=None, max_length=70000)
    include_pdf: bool | None = None
    refresh: bool = False


class ApproveBody(Strict):
    package_hash: str = Field(min_length=16, max_length=128)
    confirmation: str = Field(max_length=20)


class ResolveBody(Strict):
    delivered: bool


def install_meeting_email_routes(app, require_owner_session, core) -> None:
    owner = [Depends(require_owner_session)]
    owner_change = [Depends(require_owner_session), Depends(require_csrf)]

    async def forward(call):
        try:
            return JSONResponse(await call(), headers=_NO_STORE)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (404, 409, 422, 503):
                try:
                    detail = exc.response.json().get("detail", "Request refused")
                except (ValueError, AttributeError):
                    detail = "Request refused"
                if isinstance(detail, dict):  # core's {"message", "code"}: keep the two fixed fields only
                    detail = {"message": str(detail.get("message", "Request refused"))[:300], "code": str(detail.get("code", "rejected"))[:40]}
                else:
                    detail = str(detail)[:200]
                raise HTTPException(status, detail) from None
            raise HTTPException(502, "Meeting email unavailable") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Meeting email unavailable") from None

    def req(method: str, path: str, body: BaseModel | None = None, *, timeout: float = 20.0):
        return lambda: core.planner_request(method, path, json=body.model_dump() if body is not None else None, timeout=timeout)

    @app.get(api.CONFIG, dependencies=owner)
    async def config():
        try:
            return JSONResponse(await core.planner_request("GET", api.CONFIG), headers=_NO_STORE)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:  # core does not have the feature on
                return JSONResponse({"enabled": False}, headers=_NO_STORE)
            raise HTTPException(502, "Meeting email unavailable") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Meeting email unavailable") from None

    # the dedicated sender
    @app.get(api.SENDER, dependencies=owner)
    async def get_sender():
        return await forward(req("GET", api.SENDER))

    @app.put(api.SENDER, dependencies=owner_change)
    async def put_sender(body: SenderBody):
        return await forward(req("PUT", api.SENDER, body))

    @app.post(api.SENDER_VERIFY, dependencies=owner_change)
    async def verify_sender():
        return await forward(req("POST", api.SENDER_VERIFY, timeout=60.0))  # connects to the mail server; sends nothing

    @app.post(api.SENDER_TEST, dependencies=owner_change)
    async def test_sender(body: SenderTestBody):
        return await forward(req("POST", api.SENDER_TEST, body, timeout=60.0))  # sends one fixed test message to the typed address; core enforces everything

    @app.put(api.SENDER_ENABLED, dependencies=owner_change)
    async def set_enabled(body: EnabledBody):
        return await forward(req("PUT", api.SENDER_ENABLED, body))

    @app.delete(api.SENDER, dependencies=owner_change)
    async def disconnect_sender():
        return await forward(req("DELETE", api.SENDER))

    # saved recipient groups
    @app.get(api.GROUPS, dependencies=owner)
    async def list_groups():
        return await forward(req("GET", api.GROUPS))

    @app.post(api.GROUPS, dependencies=owner_change)
    async def create_group(body: GroupBody):
        return await forward(req("POST", api.GROUPS, body))

    @app.put(api.GROUP, dependencies=owner_change)
    async def update_group(body: GroupBody, group_id: str = Path(pattern=_ID)):
        return await forward(req("PUT", f"{api.GROUPS}/{quote(group_id, safe='')}", body))

    @app.delete(api.GROUP, dependencies=owner_change)
    async def delete_group(group_id: str = Path(pattern=_ID)):
        return await forward(req("DELETE", f"{api.GROUPS}/{quote(group_id, safe='')}"))

    # a meeting's package
    @app.post(api.MEETING_PREPARE, dependencies=owner_change)
    async def prepare(body: PrepareBody, meeting_id: str = Path(pattern=_ID)):
        return await forward(req("POST", f"/meetings/{quote(meeting_id, safe='')}/email/prepare", body, timeout=30.0))

    @app.get(api.MEETING_SUGGESTIONS, dependencies=owner)
    async def suggestions(meeting_id: str = Path(pattern=_ID)):
        return await forward(req("GET", f"/meetings/{quote(meeting_id, safe='')}/email/suggestions"))

    @app.get(api.DRAFTS, dependencies=owner)
    async def list_drafts(meeting_id: str | None = None):
        path = api.DRAFTS + (f"?meeting_id={quote(meeting_id, safe='')}" if meeting_id and len(meeting_id) <= 64 else "")
        return await forward(req("GET", path))

    @app.get(api.DRAFT, dependencies=owner)
    async def get_draft(draft_id: str = Path(pattern=_ID)):
        return await forward(req("GET", f"{api.DRAFTS}/{quote(draft_id, safe='')}"))

    @app.put(api.DRAFT, dependencies=owner_change)
    async def edit_draft(body: EditBody, draft_id: str = Path(pattern=_ID)):
        return await forward(req("PUT", f"{api.DRAFTS}/{quote(draft_id, safe='')}", body, timeout=30.0))

    @app.post(api.DRAFT_APPROVE, dependencies=owner_change)
    async def approve(body: ApproveBody, draft_id: str = Path(pattern=_ID)):
        return await forward(req("POST", f"{api.DRAFTS}/{quote(draft_id, safe='')}/approve", body))

    @app.post(api.DRAFT_QUEUE, dependencies=owner_change)
    async def queue(draft_id: str = Path(pattern=_ID)):
        return await forward(req("POST", f"{api.DRAFTS}/{quote(draft_id, safe='')}/queue"))

    @app.post(api.DRAFT_CANCEL_SEND, dependencies=owner_change)
    async def cancel_send(draft_id: str = Path(pattern=_ID)):
        return await forward(req("POST", f"{api.DRAFTS}/{quote(draft_id, safe='')}/cancel-send"))

    @app.post(api.DRAFT_DISCARD, dependencies=owner_change)
    async def discard(draft_id: str = Path(pattern=_ID)):
        return await forward(req("POST", f"{api.DRAFTS}/{quote(draft_id, safe='')}/discard"))

    @app.post(api.DRAFT_RESOLVE, dependencies=owner_change)
    async def resolve(body: ResolveBody, draft_id: str = Path(pattern=_ID)):
        return await forward(req("POST", f"{api.DRAFTS}/{quote(draft_id, safe='')}/resolve", body))

    @app.get(api.DRAFT_ATTACHMENT, dependencies=owner)
    async def attachment(draft_id: str = Path(pattern=_ID), name: str = Path(pattern=r"^[A-Za-z0-9._-]{1,120}$")):
        """The attachment exactly as it would be sent, for the owner's preview. Served inline with no sniffing and no caching."""
        try:
            upstream = await core.document_request("GET", f"{api.DRAFTS}/{quote(draft_id, safe='')}/attachments/{quote(name, safe='')}", timeout=30.0)
        except httpx.HTTPError:
            raise HTTPException(502, "Meeting email unavailable") from None
        if upstream.status_code != 200:
            raise HTTPException(upstream.status_code if upstream.status_code in (404, 409) else 502, "No such attachment" if upstream.status_code == 404 else "Meeting email unavailable")
        return Response(upstream.content, media_type=upstream.headers.get("content-type", "application/octet-stream"), headers={
            **_NO_STORE, "Content-Disposition": f'inline; filename="{name}"', "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})
