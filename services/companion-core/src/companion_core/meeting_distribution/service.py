"""Supervised meeting-minutes email: preparation, review, approval and queueing (Phase 55, ADR 0039).

The state machine is `DRAFT -> READY_FOR_REVIEW -> APPROVED -> QUEUED -> SENDING -> SENT` with `CANCELLED`, `FAILED` and `UNKNOWN_DELIVERY`. This service owns the owner-facing steps up to QUEUED;
the existing dispatch loop (`email/workflow.py`) owns everything from QUEUED on, and is the only code that sends. Approval and queueing are text-only (ADR 0011) and bound to a hash of the exact
package; any edit returns the package to review. Nothing here regenerates approved content at dispatch time."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from companion_core.consent.gate import require_text
from companion_core.email.mime import (
    AddressError,
    clean_body,
    clean_recipients,
    clean_subject,
    normalize_address,
)
from companion_core.email.models import (
    MEETING_MINUTES_KIND,
    SENDER_TEST_KIND,
    DraftStatus,
    EmailDraft,
    Recipients,
)
from companion_core.email.sender_config import MailSenderStore
from companion_core.email.store import EmailStore
from companion_core.email.workflow import (
    DEFAULT_SEND_DELAY_SECONDS,
    DraftNotQueuedError,
    SendFn,
    cancel_queued_draft,
    dispatch_due_drafts,
)
from companion_core.meeting_distribution import package as pkg
from companion_core.meeting_distribution.groups import GroupStore
from companion_core.meetings.models import READY_FOR_OUTPUTS, Meeting
from shared.models.response import Privacy
from shared.models.session import InputModality

CONFIRM_WORD = "SEND"
TEST_PER_HOUR = 5  # a test is for checking the account, not for sending mail: a handful an hour is plenty
TEST_MIN_GAP_SECONDS = 10


class DistributionError(Exception):
    def __init__(self, status: int, detail: str, code: str = "rejected") -> None:
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code


class MeetingEmailService:
    def __init__(
        self,
        *,
        emails: EmailStore,
        meetings: Any,
        senders: MailSenderStore,
        groups: GroupStore,
        analysis: Any | None = None,
        timezone: Callable[[], Awaitable[str]] | None = None,
        owner_emails: Callable[[], Awaitable[list[str]]] | None = None,
        attendees: Callable[[Meeting], Awaitable[list[str]]] | None = None,
        delay_seconds: int = DEFAULT_SEND_DELAY_SECONDS,
        send_fn: SendFn | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.emails, self.meetings, self.senders, self.groups, self.analysis = emails, meetings, senders, groups, analysis
        self._timezone, self._owner_emails, self._attendees, self.delay_seconds, self.clock = timezone, owner_emails, attendees, delay_seconds, clock
        self._send_fn = send_fn

    # -- helpers -------------------------------------------------------------------------------------------------------------------------------

    async def _meeting(self, meeting_id: str) -> Meeting:
        meeting = await self.meetings.get_meeting(meeting_id)
        if meeting is None:
            raise DistributionError(404, "No such meeting", "not_found")
        return meeting

    async def _draft(self, draft_id: str) -> EmailDraft:
        draft = await self.emails.get_draft(draft_id)
        if draft is None or draft.kind != MEETING_MINUTES_KIND:
            raise DistributionError(404, "No such draft", "not_found")
        return draft

    async def _sender_address(self) -> str:
        settings = await self.senders.get()
        if not settings.configured:
            raise DistributionError(409, "Set up the outbound sender first (Settings, Outbound meeting email).", "no_sender")
        return normalize_address(settings.from_address)

    async def _analysis_view(self, meeting_id: str) -> dict | None:
        if self.analysis is None:
            return None
        try:
            return await self.analysis.status(meeting_id)
        except Exception:  # noqa: BLE001 - a missing analysis must not stop minutes from being prepared
            return None

    async def _expand(self, group_ids: list[str] | None) -> list[str]:
        out: list[str] = []
        for group_id in group_ids or []:
            group = await self.groups.get(group_id)
            if group is None:
                raise DistributionError(404, "No such recipient group", "not_found")
            out += group.addresses
        return out

    def _recipients(self, to: list[str], cc: list[str], bcc: list[str]) -> Recipients:
        try:
            return clean_recipients(to, cc, bcc, require_to=False)  # a draft may be prepared before anyone is chosen; approval requires a To
        except AddressError as exc:
            raise DistributionError(422, str(exc), "bad_recipients") from None

    async def _view(self, draft: EmailDraft, *, warnings: list[str] | None = None) -> dict:
        events = await self.emails.list_events(draft.id)
        meeting = await self.meetings.get_meeting((draft.source or {}).get("meeting_id", ""))
        settings = await self.senders.get()
        prepared = next((e for e in events if e.event == "prepared"), None)
        data = draft.model_dump(mode="json", exclude={"attachment_blobs"})
        data.update({
            "meeting_title": meeting.title if meeting else None,
            "meeting_changed": bool(meeting is None or not pkg.source_is_current(draft.source or {}, meeting)),
            "sender_ready": bool(settings.configured and settings.enabled),
            "events": [{"at": e.at.isoformat(), "event": e.event, "detail": e.detail} for e in events],
            "warnings": warnings if warnings is not None else (prepared.detail.get("warnings", []) if prepared else []),
            "recipient_count": len((draft.recipients or Recipients()).everyone()),
        })
        return data

    # -- config, groups, suggestions -----------------------------------------------------------------------------------------------------------

    async def config(self) -> dict:
        settings = await self.senders.get()
        return {"enabled": True, "sender": settings.view(), "send_delay_seconds": self.delay_seconds, "confirm_word": CONFIRM_WORD}

    async def suggestions(self, meeting_id: str) -> list[dict]:
        """Addresses the owner MAY choose: invitees of the calendar event at the meeting's time, and participant entries that are already addresses. Nothing is preselected or emailed
        automatically, the owner's own addresses and the sender are left out, and speakers are never turned into addresses."""
        meeting = await self._meeting(meeting_id)
        skip = {a.lower() for a in (await self._owner_emails() if self._owner_emails else [])}
        settings = await self.senders.get()
        if settings.from_address:
            skip.add(settings.from_address.lower())
        found: dict[str, str] = {}
        for raw in meeting.participants:
            try:
                found.setdefault(normalize_address(raw), "participant entry")
            except AddressError:
                pass
        for raw in (await self._attendees(meeting) if self._attendees else []):
            try:
                found.setdefault(normalize_address(raw), "calendar invitee")
            except AddressError:
                pass
        return [{"address": a, "source": s} for a, s in sorted(found.items()) if a not in skip]

    # -- preparation and editing ---------------------------------------------------------------------------------------------------------------

    async def prepare(self, meeting_id: str, *, allow_sensitive: bool = False, include_pdf: bool = True, to: list[str] | None = None, cc: list[str] | None = None,
                      bcc: list[str] | None = None, group_ids: list[str] | None = None) -> dict:
        meeting = await self._meeting(meeting_id)
        if meeting.status not in READY_FOR_OUTPUTS or not meeting.transcript_segments:
            raise DistributionError(409, "This meeting has no processed transcript yet.", "not_ready")
        if not (meeting.summary or meeting.minutes):
            raise DistributionError(409, "Write the summary and minutes first.", "no_outputs")
        if meeting.stale_outputs:
            raise DistributionError(409, f"The {' and '.join(meeting.stale_outputs)} was written before the speaker names changed. Write it again first.", "stale_outputs")
        if meeting.speaker_identity.superseded and meeting.speaker_identity.superseded.identities:
            raise DistributionError(409, "Speaker detection was run again and the speaker names are not confirmed. Identify the speakers first.", "speakers_unconfirmed")
        if meeting.sensitivity is Privacy.SENSITIVE and not allow_sensitive:
            raise DistributionError(409, "This meeting is marked sensitive. Confirm that you want to prepare a message from it.", "sensitive_meeting")
        sender = await self._sender_address()
        recipients = self._recipients([*(to or []), *await self._expand(group_ids)], cc or [], bcc or [])
        built = pkg.build(meeting, await self._analysis_view(meeting_id), timezone=await self._timezone() if self._timezone else "UTC", include_pdf=include_pdf,
                          sensitive_acknowledged=bool(allow_sensitive and meeting.sensitivity is Privacy.SENSITIVE))
        blobs = [(built.pdf_name, "application/pdf", built.pdf)] if built.pdf else []
        draft = EmailDraft(to=recipients.to[0] if recipients.to else "", subject=built.subject, body=built.body, status=DraftStatus.READY_FOR_REVIEW, kind=MEETING_MINUTES_KIND,
                           recipients=recipients, source=built.source, sender=sender)
        saved = await self.emails.create_package(draft, blobs)
        await self.emails.add_event(saved.id, "prepared", {"meeting_id": meeting_id, "warnings": built.warnings, "attachments": [b[0] for b in blobs], "counts": built.counts})
        return await self._view(saved, warnings=built.warnings)

    async def update(self, draft_id: str, *, to: list[str] | None = None, cc: list[str] | None = None, bcc: list[str] | None = None, group_ids: list[str] | None = None,
                     subject: str | None = None, body: str | None = None, include_pdf: bool | None = None, refresh: bool = False) -> dict:
        draft = await self._draft(draft_id)
        if draft.status not in (DraftStatus.DRAFT, DraftStatus.READY_FOR_REVIEW, DraftStatus.APPROVED):
            raise DistributionError(409, f"A message that is {draft.status.value.replace('_', ' ')} cannot be edited. Cancel it first.", "not_editable")
        current = draft.recipients or Recipients()
        merged_to = (to if to is not None else current.to) + await self._expand(group_ids)
        recipients = self._recipients(merged_to, cc if cc is not None else current.cc, bcc if bcc is not None else current.bcc)
        new_subject, new_body, source, blobs = draft.subject, draft.body, draft.source or {}, None
        has_pdf = bool(draft.attachments)
        want_pdf = has_pdf if include_pdf is None else include_pdf
        if refresh or (want_pdf and not has_pdf):
            meeting = await self._meeting(source.get("meeting_id", ""))
            if meeting.stale_outputs:
                raise DistributionError(409, "The summary or minutes is out of date with the speaker names. Write it again first.", "stale_outputs")
            built = pkg.build(meeting, await self._analysis_view(meeting.id), timezone=await self._timezone() if self._timezone else "UTC", include_pdf=want_pdf,
                              sensitive_acknowledged=bool(source.get("sensitive_acknowledged")))
            source = built.source
            if refresh:
                new_subject, new_body = built.subject, built.body
            blobs = [(built.pdf_name, "application/pdf", built.pdf)] if built.pdf else []
            if want_pdf and not built.pdf:
                raise DistributionError(422, built.pdf_error or "The PDF could not be made.", "pdf_failed")
        elif not want_pdf and has_pdf:
            blobs = []
        try:
            if subject is not None:
                new_subject = clean_subject(subject)
            if body is not None:
                new_body = clean_body(body)
        except AddressError as exc:
            raise DistributionError(422, str(exc), "bad_content") from None
        sender = await self._sender_address()
        updated = await self.emails.update_package(draft_id, recipients=recipients, subject=new_subject, body=new_body, sender=sender, blobs=blobs, source=source)
        if updated is None:
            raise DistributionError(409, "This message can no longer be edited.", "not_editable")
        await self.emails.add_event(draft_id, "edited", {"refreshed": refresh, "recipients": updated.recipients.everyone() if updated.recipients else [], "attachments": [a.name for a in updated.attachments]})
        return await self._view(updated)

    # -- approval and queueing (text only) -----------------------------------------------------------------------------------------------------

    async def approve(self, draft_id: str, *, package_hash: str, confirmation: str, modality: InputModality = InputModality.TEXT) -> dict:
        require_text(modality)  # ADR 0011: authorising an outbound message is never accepted from voice
        if (confirmation or "").strip().upper() != CONFIRM_WORD:
            raise DistributionError(422, f"Type {CONFIRM_WORD} to approve this message.", "confirmation_required")
        draft = await self._draft(draft_id)
        if draft.status is not DraftStatus.READY_FOR_REVIEW:
            raise DistributionError(409, f"A message that is {draft.status.value.replace('_', ' ')} cannot be approved.", "bad_state")
        if not draft.recipients or not draft.recipients.to:
            raise DistributionError(422, "Add at least one To recipient before approving.", "no_recipients")
        sender = await self._sender_address()
        if draft.sender != sender:
            raise DistributionError(409, "The sender changed since this message was prepared. Review it again.", "sender_changed")
        if package_hash != draft.package_hash:
            raise DistributionError(409, "The message changed since you reviewed it. Review it again.", "changed")
        message_id = f"<{uuid.uuid4().hex}@{sender.rpartition('@')[2]}>"
        approved = await self.emails.approve_reviewed(draft_id, package_hash=package_hash, message_id=message_id)
        if approved is None:
            raise DistributionError(409, "The message changed or was already approved.", "changed")
        await self.emails.add_event(draft_id, "approved", {"package_hash": package_hash, "recipients": approved.recipients.everyone() if approved.recipients else [], "attachment_hashes": [a.sha256 for a in approved.attachments]})
        return await self._view(approved)

    async def queue(self, draft_id: str, *, modality: InputModality = InputModality.TEXT) -> dict:
        require_text(modality)
        draft = await self._draft(draft_id)
        if draft.status is not DraftStatus.APPROVED:
            raise DistributionError(409, f"A message that is {draft.status.value.replace('_', ' ')} cannot be queued.", "bad_state")
        settings = await self.senders.get()
        if not (settings.configured and settings.enabled):
            raise DistributionError(409, "Sending is turned off. Enable the outbound sender in Settings first.", "sending_off")
        meeting = await self.meetings.get_meeting((draft.source or {}).get("meeting_id", ""))
        if meeting is None or not pkg.source_is_current(draft.source or {}, meeting):
            raise DistributionError(409, "The meeting changed since this message was prepared (summary, minutes or speaker names). Refresh the message and review it again.", "meeting_changed")
        if await self._sender_address() != draft.sender:
            raise DistributionError(409, "The sender changed since this message was approved. Review it again.", "sender_changed")
        queued = await self.emails.queue_draft(draft_id, dispatch_at=self.clock() + timedelta(seconds=self.delay_seconds))
        if queued is None:
            raise DistributionError(409, "This message was already queued or changed.", "bad_state")
        await self.emails.add_event(draft_id, "queued", {"dispatch_at": queued.dispatch_at.isoformat() if queued.dispatch_at else None})
        return await self._view(queued)

    async def cancel_send(self, draft_id: str) -> dict:
        """The undo, from any channel: back to APPROVED, nothing sent. Never gated."""
        await self._draft(draft_id)
        try:
            cancelled = await cancel_queued_draft(self.emails, draft_id)
        except DraftNotQueuedError:
            raise DistributionError(409, "This message is not waiting to be sent (it may already be sending).", "bad_state") from None
        await self.emails.add_event(draft_id, "cancelled_before_send", {})
        return await self._view(cancelled)

    async def discard(self, draft_id: str) -> dict:
        await self._draft(draft_id)
        discarded = await self.emails.discard_draft(draft_id)
        if discarded is None:
            raise DistributionError(409, "This message cannot be discarded now.", "bad_state")
        await self.emails.add_event(draft_id, "discarded", {})
        return await self._view(discarded)

    async def resolve(self, draft_id: str, *, delivered: bool, modality: InputModality = InputModality.TEXT) -> dict:
        """The owner settles an unknown outcome: it arrived (mark sent), or it did not (send it again, which needs a fresh review and approval)."""
        require_text(modality)
        await self._draft(draft_id)
        settled = await self.emails.resolve_unknown(draft_id, delivered=delivered)
        if settled is None:
            raise DistributionError(409, "Only a message with an unknown delivery can be settled.", "bad_state")
        await self.emails.add_event(draft_id, "owner_confirmed_delivered" if delivered else "owner_reopened", {})
        return await self._view(settled)

    # -- the sender test -----------------------------------------------------------------------------------------------------------------------

    async def send_test(self, to: str, *, modality: InputModality = InputModality.TEXT) -> dict:
        """The owner's deliberate one-off test of the dedicated sender, to the single address typed in Settings. The message is fixed text with no meeting content and no attachment, it needs
        the sender to be configured, verified and switched on (so "off" really means off), and it is limited to a few an hour. It is an ordinary stored draft sent by the existing dispatch
        loop's code path (claimed, hash-checked, recorded in the draft's history), immediately instead of after the undo window: the owner is waiting for the answer, the content is
        fixed, and it can go only to the address the owner just typed. Text only (ADR 0011)."""
        require_text(modality)
        try:
            recipient = normalize_address(to)
        except AddressError as exc:
            raise DistributionError(422, str(exc), "bad_recipient") from None
        settings = await self.senders.get()
        if not settings.configured:
            raise DistributionError(409, "Set up the outbound sender first.", "no_sender")
        if not settings.enabled:
            raise DistributionError(409, "Sending is turned off. Verify the connection and turn sending on first.", "sending_off")
        now = self.clock()
        recent = [d for d in await self.emails.list_drafts(kind=SENDER_TEST_KIND) if now - d.created_at < timedelta(hours=1)]
        if len(recent) >= TEST_PER_HOUR or any(now - d.created_at < timedelta(seconds=TEST_MIN_GAP_SECONDS) for d in recent):
            raise DistributionError(409, f"Test emails are limited to {TEST_PER_HOUR} an hour. Wait a little and try again.", "rate_limited")
        sender = await self._sender_address()
        body = (
            f"This is a test message from Reachy.\n\nIt was sent at {now.strftime('%Y-%m-%d %H:%M')} UTC from {sender}, because the owner asked for a test of the outbound email account.\n"
            "If you received it, the account works. It contains no meeting content and no attachment, and nothing else will follow from it.\n"
        )
        draft = EmailDraft(to=recipient, subject="Reachy test email", body=body, status=DraftStatus.READY_FOR_REVIEW, kind=SENDER_TEST_KIND, recipients=Recipients(to=[recipient]),
                           source={"purpose": "sender_test"}, sender=sender)
        saved = await self.emails.create_package(draft, [])
        approved = await self.emails.approve_reviewed(saved.id, package_hash=saved.package_hash or "", message_id=f"<{uuid.uuid4().hex}@{sender.rpartition('@')[2]}>")
        await self.emails.add_event(saved.id, "prepared", {"purpose": "sender_test", "recipient": recipient})
        if approved is None or await self.emails.queue_draft(saved.id, dispatch_at=now) is None:
            raise DistributionError(409, "The test message could not be queued.", "bad_state")
        await self.emails.add_event(saved.id, "approved", {"recipients": [recipient]})
        await self.emails.add_event(saved.id, "queued", {"dispatch_at": now.isoformat()})
        if self._send_fn is not None:
            await dispatch_due_drafts(self.emails, send_fn=self._send_fn, now=now + timedelta(seconds=1))  # the same claim, hash check and outcome handling as every send
        for _ in range(40):  # a loop pass may have claimed it a moment earlier: wait briefly for the outcome
            final = await self.emails.get_draft(saved.id)
            if final is not None and final.status not in (DraftStatus.QUEUED, DraftStatus.SENDING):
                break
            await asyncio.sleep(0.25)
        final = await self.emails.get_draft(saved.id)
        return {"id": saved.id, "status": final.status.value if final else "unknown", "to": recipient, "provider_response": final.provider_response if final else None,
                "error": final.last_error if final and final.status in (DraftStatus.FAILED, DraftStatus.UNKNOWN_DELIVERY) else None}

    # -- reads ---------------------------------------------------------------------------------------------------------------------------------

    async def get(self, draft_id: str) -> dict:
        return await self._view(await self._draft(draft_id))

    async def list(self, meeting_id: str | None = None) -> list[dict]:
        drafts = await self.emails.list_drafts(kind=MEETING_MINUTES_KIND)
        if meeting_id is not None:
            drafts = [d for d in drafts if (d.source or {}).get("meeting_id") == meeting_id]
        return [await self._view(d) for d in reversed(drafts)]

    async def attachment(self, draft_id: str, name: str) -> tuple[str, bytes]:
        await self._draft(draft_id)
        for blob_name, content_type, data in await self.emails.get_blobs(draft_id):
            if blob_name == name:
                return content_type, data
        raise DistributionError(404, "No such attachment", "not_found")

