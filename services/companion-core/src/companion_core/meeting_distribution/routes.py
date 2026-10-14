"""Core routes for the supervised meeting-minutes email (ADR 0039). They sit behind the service token like every other core route. Approve, queue and settle are text-only (ADR 0011):
the modality is fixed to TEXT here because only the conversational path can produce VOICE and no conversational handler reaches a meeting package. Errors carry a fixed message, never a credential."""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from companion_core.email.sender import MailSender
from companion_core.email.sender_config import (
    MailSenderStore,
    SenderConfigError,
    SenderSettings,
)
from companion_core.meeting_distribution.groups import GroupError, GroupStore
from companion_core.meeting_distribution.service import (
    DistributionError,
    MeetingEmailService,
)
from shared.models.session import InputModality
from shared.protocols import meeting_email_api as api


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SenderBody(Strict):
    host: str = Field(max_length=253)
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["starttls", "none"] = "starttls"
    from_address: str = Field(max_length=254)
    username: str = Field(default="", max_length=254)
    password: str | None = Field(default=None, max_length=256, repr=False)  # write-only: stored in the SecretStore, never returned or logged
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


def _raise(exc: DistributionError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"message": exc.detail, "code": exc.code})


def install_meeting_email_routes(app: FastAPI) -> None:
    def svc() -> MeetingEmailService:
        service = app.state.meeting_email
        if service is None:
            raise HTTPException(status_code=404, detail="Not found")
        return service

    def senders() -> MailSenderStore:
        return svc().senders

    def groups() -> GroupStore:
        return svc().groups

    async def run(coro):
        try:
            return await coro
        except DistributionError as exc:
            raise _raise(exc) from None

    @app.get(api.CONFIG)
    async def config() -> dict:
        return await svc().config()

    # -- the dedicated sender ------------------------------------------------------------------------------------------------------------------

    @app.get(api.SENDER)
    async def get_sender() -> dict:
        return (await senders().get()).view()

    @app.put(api.SENDER)
    async def put_sender(body: SenderBody) -> dict:
        settings = SenderSettings(host=body.host.strip(), port=body.port, security=body.security, from_address=body.from_address.strip(), username=body.username.strip())
        try:
            return (await senders().save(settings, password=body.password or None, clear_password=body.clear_password)).view()
        except SenderConfigError as exc:
            raise HTTPException(status_code=422, detail={"message": str(exc), "code": "bad_sender"}) from None

    @app.post(api.SENDER_VERIFY)
    async def verify_sender() -> dict:
        """Connect, negotiate TLS and sign in, then quit. No message is sent and no recipient is involved."""
        result = await MailSender(senders(), allow_env=False, tls_context=getattr(app.state, "mail_tls_context", None)).verify()
        settings = await senders().record_verification(bool(result["ok"]), result["detail"])
        return {**result, "sender": settings.view()}

    @app.put(api.SENDER_ENABLED)
    async def set_sender_enabled(body: EnabledBody) -> dict:
        try:
            return (await senders().set_enabled(body.enabled)).view()
        except SenderConfigError as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "code": "not_verified"}) from None

    @app.post(api.SENDER_TEST)
    async def test_sender(body: SenderTestBody) -> dict:
        """Send one fixed test message to the address the owner typed. Needs the sender enabled; text-only and owner-session-only; limited to a few an hour."""
        return await run(svc().send_test(body.to, modality=InputModality.TEXT))

    @app.delete(api.SENDER)
    async def disconnect_sender() -> dict:
        """Remove the sender: its stored credential is deleted and sending stops. Queued messages stay queued and fail safely until a sender is configured again."""
        return (await senders().disconnect()).view()

    # -- recipient groups ----------------------------------------------------------------------------------------------------------------------

    @app.get(api.GROUPS)
    async def list_groups() -> list[dict]:
        return [g.model_dump(mode="json") for g in await groups().list()]

    @app.post(api.GROUPS)
    async def create_group(body: GroupBody) -> dict:
        try:
            return (await groups().save(body.name, body.addresses)).model_dump(mode="json")
        except GroupError as exc:
            raise HTTPException(status_code=422, detail={"message": str(exc), "code": "bad_group"}) from None

    @app.put(api.GROUP)
    async def update_group(group_id: str, body: GroupBody) -> dict:
        try:
            group = await groups().save(body.name, body.addresses, group_id)
        except GroupError as exc:
            raise HTTPException(status_code=422, detail={"message": str(exc), "code": "bad_group"}) from None
        if group is None:
            raise HTTPException(status_code=404, detail="No such group")
        return group.model_dump(mode="json")

    @app.delete(api.GROUP)
    async def delete_group(group_id: str) -> dict:
        if not await groups().delete(group_id):
            raise HTTPException(status_code=404, detail="No such group")
        return {"deleted": True}

    # -- drafts --------------------------------------------------------------------------------------------------------------------------------

    @app.post(api.MEETING_PREPARE)
    async def prepare(meeting_id: str, body: PrepareBody) -> dict:
        return await run(svc().prepare(meeting_id, **body.model_dump()))

    @app.get(api.MEETING_SUGGESTIONS)
    async def suggestions(meeting_id: str) -> list[dict]:
        return await run(svc().suggestions(meeting_id))

    @app.get(api.DRAFTS)
    async def list_drafts(meeting_id: str | None = None) -> list[dict]:
        return await svc().list(meeting_id)

    @app.get(api.DRAFT)
    async def get_draft(draft_id: str) -> dict:
        return await run(svc().get(draft_id))

    @app.put(api.DRAFT)
    async def edit_draft(draft_id: str, body: EditBody) -> dict:
        return await run(svc().update(draft_id, **body.model_dump()))

    @app.post(api.DRAFT_APPROVE)
    async def approve(draft_id: str, body: ApproveBody) -> dict:
        return await run(svc().approve(draft_id, package_hash=body.package_hash, confirmation=body.confirmation, modality=InputModality.TEXT))

    @app.post(api.DRAFT_QUEUE)
    async def queue(draft_id: str) -> dict:
        return await run(svc().queue(draft_id, modality=InputModality.TEXT))

    @app.post(api.DRAFT_CANCEL_SEND)
    async def cancel_send(draft_id: str) -> dict:
        return await run(svc().cancel_send(draft_id))

    @app.post(api.DRAFT_DISCARD)
    async def discard(draft_id: str) -> dict:
        return await run(svc().discard(draft_id))

    @app.post(api.DRAFT_RESOLVE)
    async def resolve(draft_id: str, body: ResolveBody) -> dict:
        return await run(svc().resolve(draft_id, delivered=body.delivered, modality=InputModality.TEXT))

    @app.get(api.DRAFT_ATTACHMENT)
    async def attachment(draft_id: str, name: str) -> Response:
        content_type, data = await run(svc().attachment(draft_id, name))
        return Response(data, media_type=content_type, headers={"Cache-Control": "private, no-store", "Content-Disposition": f'inline; filename="{name}"', "X-Content-Type-Options": "nosniff"})
