"""Phase 55 (ADR 0039): supervised meeting-minutes email. In-process, in-memory stores and a recording send function; real SMTP against Mailpit is in test_meeting_email_mailpit.py and real
PostgreSQL in test_meeting_email_postgres.py. Time is controlled: the dispatch step takes `now`."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.gate import VoiceConfirmationNotAllowedError
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email import mime
from companion_core.email.models import (
    MEETING_MINUTES_KIND,
    DraftStatus,
    EmailDraft,
    Recipients,
)
from companion_core.email.sender import (
    MailSender,
    SendRefused,
    SendTransient,
    SendUnknown,
)
from companion_core.email.sender_config import (
    InMemoryMailSenderStore,
    SenderConfigError,
    SenderSettings,
)
from companion_core.email.store import InMemoryEmailStore
from companion_core.email.workflow import (
    MAX_ATTEMPTS,
    dispatch_due_drafts,
    recover_interrupted,
)
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meeting_distribution import pdf as pdf_writer
from companion_core.meeting_distribution.groups import InMemoryGroupStore
from companion_core.meeting_distribution.service import CONFIRM_WORD, DistributionError
from companion_core.meetings.models import (
    MeetingJobStatus,
    MeetingOutput,
    speaker_basis,
)
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

from shared.models.response import Privacy
from shared.models.session import InputModality

SENDER = "reachy.minutes@example.test"
TOKEN = "service-secret"
HEADERS = {"X-Reachy-Service-Token": TOKEN}
NAMES = {"SPEAKER_00": "Priya Shah"}
SEGMENTS = [{"start": 0.0, "end": 5.0, "text": "SECRET-TRANSCRIPT-LINE we agree to ship on Friday."}]


class FakeAnalysis:
    """What Phase 31's status() returns, shaped like the real one."""

    def __init__(self, items=None, *, changed=False, run=True):
        self.view = {"run": {"id": "run-1"} if run else None, "transcript_changed_since_run": changed, "items": items or []}

    async def status(self, meeting_id):
        return self.view


def item(kind, status, text, **over):
    base = {"id": f"i-{text[:6]}", "kind": kind, "status": status, "text": text, "evidence": [{"segment": 0, "start": 65.0, "end": 70.0, "speaker": "Priya Shah", "quote": "we agree to ship on Friday"}],
            "assignee": "Priya Shah", "source_changed": False, "attribution_changed": False, "task_text": f"Priya Shah: {text}"}
    base.update(over)
    return base


class W:
    """A running core app with the flag on, a configured/verified/enabled sender and one completed meeting."""

    def __init__(self, *, sensitivity=Privacy.WORK_PRIVATE, with_sender=True, enabled=True):
        self.sent: list[tuple[EmailDraft, list]] = []
        self.sender_store, self.groups, self.emails, self.meetings = InMemoryMailSenderStore(), InMemoryGroupStore(), InMemoryEmailStore(), InMemoryMeetingStore()

        async def send(draft: EmailDraft) -> str:
            self.sent.append((draft, list(draft.attachment_blobs)))
            return "2.0.0 OK queued"

        self.send = send
        self.app = create_app(
            calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=self.meetings, run_meeting_worker_task=False,
            memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=self.emails, email_send_fn=send, confirmation_store=InMemoryConfirmationStore(),
            llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
            run_email_dispatch_task=False, accounts_service_token=TOKEN, meeting_email_enabled=True, mail_sender_store=self.sender_store, recipient_group_store=self.groups,
            email_send_delay_seconds=600, llm_transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        self.client = TestClient(self.app, headers=HEADERS)
        self.meeting_id = asyncio.run(self._seed(sensitivity))
        if with_sender:
            asyncio.run(self._configure(enabled))

    async def _seed(self, sensitivity):
        m = await self.meetings.create_meeting(title="Weekly sync", audio=b"RIFF....audio-bytes", source_filename="a.wav", content_type="audio/wav", participants=["Hariz"],
                                               started_at=datetime(2026, 10, 14, 6, 0, tzinfo=UTC), sensitivity=sensitivity)
        basis = speaker_basis(NAMES)
        self.meetings._touch(m, status=MeetingJobStatus.COMPLETE, transcript_segments=SEGMENTS, speaker_names=dict(NAMES),
                             summary=MeetingOutput(text="Priya Shah proposed shipping on Friday and the team agreed.", tier="local", speaker_basis=basis),
                             minutes=MeetingOutput(text="Topics discussed\n- Release date\nDecisions\n- Ship on Friday", tier="local", speaker_basis=basis))
        return m.id

    async def _configure(self, enabled):
        await self.sender_store.save(SenderSettings(host="smtp.example.test", from_address=SENDER, username=SENDER), password="app-password-1")
        await self.sender_store.record_verification(True, "ok")
        if enabled:
            await self.sender_store.set_enabled(True)

    @property
    def service(self):
        return self.app.state.meeting_email

    def analysis(self, **kw):
        self.service.analysis = FakeAnalysis(**kw)

    def prepare(self, **body):
        r = self.client.post(f"/meetings/{self.meeting_id}/email/prepare", json=body)
        assert r.status_code == 200, r.text
        return r.json()

    def approve(self, draft, *, word=CONFIRM_WORD):
        return self.client.post(f"/meeting-email/drafts/{draft['id']}/approve", json={"package_hash": draft["package_hash"], "confirmation": word})

    def ready(self, **body):
        """Prepared, recipient added, approved and queued: waiting in the 10-minute window."""
        draft = self.prepare(to=["colleague@example.org"], **body)
        approved = self.approve(draft)
        assert approved.status_code == 200, approved.text
        queued = self.client.post(f"/meeting-email/drafts/{draft['id']}/queue")
        assert queued.status_code == 200, queued.text
        return queued.json()

    def dispatch(self, minutes=11, send=None):
        return asyncio.run(dispatch_due_drafts(self.emails, send_fn=send or self.send, now=datetime.now(UTC) + timedelta(minutes=minutes)))

    def draft(self, draft_id):
        return self.client.get(f"/meeting-email/drafts/{draft_id}").json()


def code(response):
    return response.json()["detail"]["code"]


# ---- addresses, headers and messages ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "plain", "a@b", "a b@example.org", "a@example.org\r\nBcc: evil@example.net", "Name <a@example.org>", "a@@example.org", '"quoted"@example.org', "a@-x.org", "a@x.123", "a" * 70 + "@example.org"])
def test_unsafe_or_malformed_addresses_are_refused(bad):
    with pytest.raises(mime.AddressError):
        mime.normalize_address(bad)


def test_recipients_are_lowercased_deduplicated_across_lists_and_capped():
    r = mime.clean_recipients(["A@Example.org", "a@example.org"], ["b@example.org", "a@example.org"], ["c@example.org"])
    assert (r.to, r.cc, r.bcc) == (["a@example.org"], ["b@example.org"], ["c@example.org"])
    with pytest.raises(mime.AddressError):
        mime.clean_recipients([f"u{i}@example.org" for i in range(21)])
    with pytest.raises(mime.AddressError):
        mime.clean_recipients([], ["x@example.org"])  # a To is required unless explicitly relaxed


def test_the_message_has_no_injected_headers_keeps_bcc_out_of_every_header_and_carries_the_attachment():
    draft = EmailDraft(to="a@example.org", subject="Minutes", body="Hello\n\nBody", recipients=Recipients(to=["a@example.org"], cc=["b@example.org"], bcc=["secret@example.org"]), kind=MEETING_MINUTES_KIND)
    message = mime.build_message(draft, sender=SENDER, attachments=[("m.pdf", "application/pdf", b"%PDF-1.4 fake")])
    raw = message.as_bytes().decode()
    assert "secret@example.org" not in raw and "Bcc" not in raw
    assert message["To"] == "a@example.org" and message["Cc"] == "b@example.org" and message["Message-ID"].startswith("<")
    assert mime.envelope_recipients(draft) == ["a@example.org", "b@example.org", "secret@example.org"]
    assert [p.get_filename() for p in message.iter_attachments()] == ["m.pdf"]
    # a subject with a newline is collapsed to one line; it can never start a header
    assert "\n" not in mime.clean_subject("Minutes\r\nBcc: x@example.org")
    injected = mime.build_message(EmailDraft(to="x@example.org", subject="x\r\nBcc: y@example.org", body="b"), sender=SENDER)
    assert injected["Bcc"] is None and "\n" not in injected["Subject"]


def test_an_older_text_draft_with_an_unsafe_to_is_refused_by_the_real_sender_instead_of_injecting_headers():
    store = InMemoryMailSenderStore()

    async def go():
        await store.save(SenderSettings(host="smtp.example.test", from_address=SENDER), password=None)
        await store.record_verification(True, "ok")
        await store.set_enabled(True)
        with pytest.raises(SendRefused):
            await MailSender(store)(EmailDraft(to="a@example.org\r\nBcc: evil@example.net", subject="x", body="y"))

    asyncio.run(go())


# ---- the package --------------------------------------------------------------------------------------------------------------------------------

def test_the_package_uses_owner_speaker_names_and_the_stored_outputs_and_leaves_internal_material_out():
    w = W()
    w.analysis(items=[item("decision", "noted", "Ship on Friday"), item("action", "accepted", "Send the notes"), item("action", "pending", "Book the room", id="i-pending")])
    d = w.prepare()
    assert d["status"] == "ready_for_review" and d["kind"] == MEETING_MINUTES_KIND and d["recipient_count"] == 0
    body = d["body"]
    assert "Weekly sync" in body and "Wed 14 Oct 2026, 06:00 (UTC)" in body and "Priya Shah" in body
    assert "proposed shipping on Friday" in body
    assert "SECRET-TRANSCRIPT-LINE" not in body and "audio-bytes" not in body  # no transcript, no recording
    assert "Ship on Friday" in body and "not individually confirmed" in body  # a decision, labelled as automatic
    assert "Priya Shah: Send the notes" in body and "Confirmed by the owner" in body  # only the confirmed action
    assert "Book the room" not in body  # a pending candidate is never included
    assert any("1 action candidate not included" in x for x in d["warnings"])
    assert [a["name"] for a in d["attachments"]] == ["Weekly-sync-minutes-2026-10-14.pdf"] and d["attachments"][0]["content_type"] == "application/pdf"
    pdf = w.client.get(f"/meeting-email/drafts/{d['id']}/attachments/{d['attachments'][0]['name']}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-") and pdf.headers["content-type"] == "application/pdf"
    assert b"SECRET-TRANSCRIPT-LINE" not in pdf.content


def test_the_date_is_shown_in_the_owners_time_zone_with_its_name():
    w = W()

    async def singapore():
        return "Asia/Singapore"

    w.service._timezone = singapore
    assert "Wed 14 Oct 2026, 14:00 (Asia/Singapore)" in w.prepare()["body"]


def test_unconfirmed_or_out_of_date_findings_are_never_presented_as_confirmed():
    w = W()
    w.analysis(items=[item("decision", "noted", "Stale decision", attribution_changed=True), item("action", "dismissed", "Dismissed action"), item("action", "accepted", "Changed text", source_changed=True)])
    body = w.prepare()["body"]
    assert "Stale decision" not in body and "Dismissed action" not in body and "Changed text" not in body
    w.analysis(items=[item("decision", "noted", "Ship on Friday")], changed=True)  # the transcript or a speaker name changed since the analysis
    d = w.prepare()
    assert "Ship on Friday" not in d["body"] and any("out of date" in x for x in d["warnings"])
    w.analysis(items=[], run=False)  # nothing analysed: no sections, no invented findings
    assert "DECISIONS" not in w.prepare()["body"] and "ACTION ITEMS" not in w.prepare()["body"]


def test_a_summary_written_before_the_speaker_names_changed_blocks_preparation_until_it_is_written_again():
    w = W()
    asyncio.run(w.meetings.set_speaker_names(w.meeting_id, {"SPEAKER_00": "Someone Else"}))  # Phase 54: the stored outputs no longer match the names
    r = w.client.post(f"/meetings/{w.meeting_id}/email/prepare", json={})
    assert r.status_code == 409 and code(r) == "stale_outputs"
    m = asyncio.run(w.meetings.get_meeting(w.meeting_id))
    basis = speaker_basis(m.speaker_names)
    w.meetings._touch(m, summary=MeetingOutput(text="Someone Else proposed shipping.", tier="local", speaker_basis=basis), minutes=MeetingOutput(text="Minutes", tier="local", speaker_basis=basis))
    assert "Someone Else proposed shipping." in w.prepare()["body"]  # names corrected, outputs regenerated: the package carries them


def test_a_meeting_with_unconfirmed_speakers_or_no_outputs_or_not_ready_cannot_be_prepared():
    w = W()
    w.meetings._touch(asyncio.run(w.meetings.get_meeting(w.meeting_id)), summary=None, minutes=None)
    assert code(w.client.post(f"/meetings/{w.meeting_id}/email/prepare", json={})) == "no_outputs"
    w2 = W()
    w2.meetings._touch(asyncio.run(w2.meetings.get_meeting(w2.meeting_id)), status=MeetingJobStatus.TRANSCRIBING)
    assert code(w2.client.post(f"/meetings/{w2.meeting_id}/email/prepare", json={})) == "not_ready"
    assert w2.client.post("/meetings/nope/email/prepare", json={}).status_code == 404


def test_a_sensitive_meeting_needs_an_explicit_acknowledgement_and_it_is_recorded_in_the_approved_source():
    w = W(sensitivity=Privacy.SENSITIVE)
    r = w.client.post(f"/meetings/{w.meeting_id}/email/prepare", json={})
    assert r.status_code == 409 and code(r) == "sensitive_meeting"
    d = w.prepare(allow_sensitive=True)
    assert d["source"]["sensitivity"] == "sensitive" and d["source"]["sensitive_acknowledged"] is True


def test_a_pdf_that_cannot_be_made_is_reported_and_the_message_can_still_go_without_it():
    w = W()
    m = asyncio.run(w.meetings.get_meeting(w.meeting_id))
    basis = speaker_basis(NAMES)
    w.meetings._touch(m, minutes=MeetingOutput(text="Minutes for Nguyễn Văn A", tier="local", speaker_basis=basis))
    d = w.prepare()
    assert d["attachments"] == [] and any("PDF could not be made" in x for x in d["warnings"]) and "Nguyễn" in d["body"]  # no attachment: the minutes are in the body instead
    assert "MINUTES" in d["body"]
    refused = w.client.put(f"/meeting-email/drafts/{d['id']}", json={"include_pdf": True})
    assert refused.status_code == 422 and code(refused) == "pdf_failed"
    assert pdf_writer.render("t", [("p", "plain ascii")]).startswith(b"%PDF")
    with pytest.raises(pdf_writer.PdfError):
        pdf_writer.render("t", [("p", "Nguyễn")])


# ---- recipients ---------------------------------------------------------------------------------------------------------------------------------

def test_recipients_are_validated_shown_in_full_and_a_to_is_required_for_approval():
    w = W()
    assert w.client.post(f"/meetings/{w.meeting_id}/email/prepare", json={"to": ["not-an-address"]}).status_code == 422
    d = w.prepare(cc=["b@example.org"], bcc=["c@example.org"])
    assert d["recipients"] == {"to": [], "cc": ["b@example.org"], "bcc": ["c@example.org"]} and d["recipient_count"] == 2
    r = w.approve(d)
    assert r.status_code == 422 and code(r) == "no_recipients"
    edited = w.client.put(f"/meeting-email/drafts/{d['id']}", json={"to": ["A@Example.org"]}).json()
    assert edited["recipients"]["to"] == ["a@example.org"] and edited["recipient_count"] == 3


def test_saved_groups_only_fill_the_list_and_nothing_is_automatic():
    w = W()
    g = w.client.post("/meeting-email/groups", json={"name": "Project team", "addresses": ["x@example.org", "y@example.org"]}).json()
    assert w.client.post("/meeting-email/groups", json={"name": "project TEAM", "addresses": ["z@example.org"]}).status_code == 422  # names are unique
    assert w.client.post("/meeting-email/groups", json={"name": "Bad", "addresses": ["nope"]}).status_code == 422
    d = w.prepare(group_ids=[g["id"]], to=["me@example.org"])
    assert d["recipients"]["to"] == ["me@example.org", "x@example.org", "y@example.org"] and d["status"] == "ready_for_review"
    assert w.sent == [] and w.dispatch() == 0  # choosing a group sent nothing
    assert w.client.put(f"/meeting-email/groups/{g['id']}", json={"name": "Project team", "addresses": ["x@example.org"]}).json()["addresses"] == ["x@example.org"]
    assert w.client.delete(f"/meeting-email/groups/{g['id']}").json() == {"deleted": True} and w.client.get("/meeting-email/groups").json() == []
    assert w.client.post(f"/meetings/{w.meeting_id}/email/prepare", json={"group_ids": ["missing"]}).status_code == 404


def test_suggestions_come_from_the_calendar_event_and_participant_addresses_only_and_are_never_preselected():
    w = W()

    async def attendees(meeting):
        return ["Dana.Lee@Example.org", "owner@example.org", SENDER, "not an address"]

    async def owners():
        return ["owner@example.org"]

    w.service._attendees, w.service._owner_emails = attendees, owners
    w.meetings._touch(asyncio.run(w.meetings.get_meeting(w.meeting_id)), participants=["Hariz", "visitor@example.org"])
    got = w.client.get(f"/meetings/{w.meeting_id}/email/suggestions").json()
    assert got == [{"address": "dana.lee@example.org", "source": "calendar invitee"}, {"address": "visitor@example.org", "source": "participant entry"}]
    assert "Priya Shah" not in str(got)  # a diarized speaker is never turned into an address
    assert w.prepare()["recipient_count"] == 0  # suggestions are offered, never applied


# ---- the state machine --------------------------------------------------------------------------------------------------------------------------

def test_the_happy_path_sends_exactly_the_approved_package_once_after_the_delay():
    w = W()
    queued = w.ready()
    assert queued["status"] == "queued" and queued["dispatch_at"] and queued["approved_hash"] == queued["package_hash"]
    assert w.dispatch(minutes=1) == 0 and w.sent == []  # inside the undo window nothing goes out
    assert w.dispatch(minutes=11) == 1 and len(w.sent) == 1
    sent, blobs = w.sent[0]
    assert sent.subject == queued["subject"] and sent.body == queued["body"] and sent.sender == SENDER and sent.message_id == queued["message_id"]
    assert [(n, c) for n, c, _ in blobs] == [("Weekly-sync-minutes-2026-10-14.pdf", "application/pdf")]
    final = w.draft(queued["id"])
    assert final["status"] == "sent" and final["provider_response"] == "2.0.0 OK queued" and final["attempts"] == 1 and final["sent_at"]
    assert [e["event"] for e in final["events"]] == ["prepared", "approved", "queued", "sending", "sent"]
    assert w.dispatch(minutes=30) == 0 and len(w.sent) == 1  # a second pass never resends


def test_approval_needs_the_typed_word_the_exact_hash_and_review_state_and_cannot_be_repeated():
    w = W()
    d = w.prepare(to=["a@example.org"])
    for word in ("", "yes", "SENDING"):
        r = w.approve(d, word=word)
        assert r.status_code == 422 and code(r) == "confirmation_required"
    wrong = w.client.post(f"/meeting-email/drafts/{d['id']}/approve", json={"package_hash": "0" * 64, "confirmation": "send"})
    assert wrong.status_code == 409 and code(wrong) == "changed"
    assert w.client.post(f"/meeting-email/drafts/{d['id']}/queue").status_code == 409  # not approved yet
    assert w.approve(d, word="send").status_code == 200  # the word is case-insensitive
    again = w.approve(d)
    assert again.status_code == 409 and code(again) == "bad_state"  # a duplicate approval
    assert w.client.post(f"/meeting-email/drafts/{d['id']}/queue").status_code == 200
    dup = w.client.post(f"/meeting-email/drafts/{d['id']}/queue")
    assert dup.status_code == 409 and code(dup) == "bad_state"  # a duplicate queue request


@pytest.mark.parametrize("change", [{"to": ["other@example.org"]}, {"cc": ["extra@example.org"]}, {"bcc": ["hidden@example.org"]}, {"subject": "A different subject"}, {"body": "Edited minutes text"}, {"include_pdf": False}])
def test_any_change_after_approval_returns_it_to_review_and_the_old_approval_cannot_send(change):
    w = W()
    d = w.prepare(to=["a@example.org"])
    assert w.approve(d).status_code == 200
    edited = w.client.put(f"/meeting-email/drafts/{d['id']}", json=change).json()
    assert edited["status"] == "ready_for_review" and edited["approved_hash"] is None and edited["package_hash"] != d["package_hash"]
    assert w.client.post(f"/meeting-email/drafts/{d['id']}/queue").status_code == 409
    stale = w.client.post(f"/meeting-email/drafts/{d['id']}/approve", json={"package_hash": d["package_hash"], "confirmation": "SEND"})
    assert stale.status_code == 409 and code(stale) == "changed"  # the hash the owner saw earlier no longer matches
    assert w.dispatch() == 0 and w.sent == []


def test_a_queued_message_cannot_be_edited_until_cancelled_then_it_returns_to_approved_and_nothing_is_sent():
    w = W()
    q = w.ready()
    blocked = w.client.put(f"/meeting-email/drafts/{q['id']}", json={"subject": "x"})
    assert blocked.status_code == 409 and code(blocked) == "not_editable"
    cancelled = w.client.post(f"/meeting-email/drafts/{q['id']}/cancel-send").json()
    assert cancelled["status"] == "approved" and cancelled["dispatch_at"] is None
    assert w.dispatch() == 0 and w.sent == []
    assert w.client.post(f"/meeting-email/drafts/{q['id']}/cancel-send").status_code == 409  # nothing queued to cancel
    discarded = w.client.post(f"/meeting-email/drafts/{q['id']}/discard").json()
    assert discarded["status"] == "cancelled"
    assert w.client.post(f"/meeting-email/drafts/{q['id']}/queue").status_code == 409


def test_regenerated_minutes_or_renamed_speakers_after_preparing_block_queueing_until_refreshed_and_reviewed():
    w = W()
    d = w.prepare(to=["a@example.org"])
    assert w.approve(d).status_code == 200
    m = asyncio.run(w.meetings.get_meeting(w.meeting_id))
    basis = speaker_basis(NAMES)
    w.meetings._touch(m, summary=MeetingOutput(text="A rewritten summary.", tier="local", speaker_basis=basis))
    r = w.client.post(f"/meeting-email/drafts/{d['id']}/queue")
    assert r.status_code == 409 and code(r) == "meeting_changed"
    assert w.draft(d["id"])["meeting_changed"] is True
    refreshed = w.client.put(f"/meeting-email/drafts/{d['id']}", json={"refresh": True}).json()
    assert "A rewritten summary." in refreshed["body"] and refreshed["status"] == "ready_for_review" and refreshed["recipients"]["to"] == ["a@example.org"]
    assert w.approve(refreshed).status_code == 200 and w.client.post(f"/meeting-email/drafts/{d['id']}/queue").status_code == 200


def test_sending_off_blocks_queueing_and_the_loop_refuses_to_send_a_queued_package():
    w = W(enabled=False)
    d = w.prepare(to=["a@example.org"])
    assert w.approve(d).status_code == 200
    r = w.client.post(f"/meeting-email/drafts/{d['id']}/queue")
    assert r.status_code == 409 and code(r) == "sending_off"
    # enabled at queue time, then switched off before dispatch: the real sender refuses and the draft fails safely
    asyncio.run(w.sender_store.set_enabled(True))
    assert w.client.post(f"/meeting-email/drafts/{d['id']}/queue").status_code == 200
    asyncio.run(w.sender_store.set_enabled(False))
    real = MailSender(w.sender_store)
    assert asyncio.run(dispatch_due_drafts(w.emails, send_fn=real, now=datetime.now(UTC) + timedelta(minutes=11))) == 0
    final = w.draft(d["id"])
    assert final["status"] == "failed" and "turned off" in final["last_error"]


def test_a_package_changed_in_storage_after_approval_is_never_sent():
    w = W()
    q = w.ready()
    stored = asyncio.run(w.emails.get_draft(q["id"]))
    stored.body = "Quietly edited after approval"  # simulates a row tampered with outside the owner's review
    assert w.dispatch() == 0 and w.sent == []
    final = w.draft(q["id"])
    assert final["status"] == "failed" and "changed after it was approved" in final["last_error"]
    w2 = W()
    q2 = w2.ready()
    w2.emails._blobs[q2["id"]] = [("Weekly-sync-minutes-2026-10-14.pdf", "application/pdf", b"%PDF-1.4 swapped")]
    assert w2.dispatch() == 0 and w2.sent == []
    assert "attachment does not match" in w2.draft(q2["id"])["last_error"]


# ---- delivery outcomes, retries and recovery -----------------------------------------------------------------------------------------------------

def test_a_refused_message_fails_without_retry_and_a_transient_one_is_retried_a_bounded_number_of_times():
    w = W()
    q = w.ready()
    calls = []

    async def refuse(draft):
        calls.append(draft.id)
        raise SendRefused("authentication failed: 535")

    assert w.dispatch(send=refuse) == 0
    failed = w.draft(q["id"])
    assert failed["status"] == "failed" and "authentication failed" in failed["last_error"] and len(calls) == 1
    assert w.dispatch(minutes=60, send=refuse) == 0 and len(calls) == 1  # nothing more is attempted

    w2 = W()
    q2 = w2.ready()
    attempts = []

    async def flaky(draft):
        attempts.append(draft.attempts)
        raise SendTransient("could not connect")

    now = datetime.now(UTC) + timedelta(minutes=11)
    for step in range(MAX_ATTEMPTS + 2):
        asyncio.run(dispatch_due_drafts(w2.emails, send_fn=flaky, now=now + timedelta(hours=step)))
    final = w2.draft(q2["id"])
    assert attempts == [1, 2, 3] and final["status"] == "failed" and "gave up after 3 attempts" in final["last_error"]
    assert [e["event"] for e in final["events"]].count("retry_scheduled") == 2


def test_an_ambiguous_outcome_is_never_retried_and_the_owner_settles_it():
    w = W()
    q = w.ready()
    calls = []

    async def lost_answer(draft):
        calls.append(1)
        raise SendUnknown("no final answer after sending: timeout")

    assert w.dispatch(send=lost_answer) == 0
    unknown = w.draft(q["id"])
    assert unknown["status"] == "unknown_delivery" and "no final answer" in unknown["last_error"]
    assert w.dispatch(minutes=120, send=w.send) == 0 and len(calls) == 1 and w.sent == []  # not retried automatically, not sent twice
    assert w.client.post(f"/meeting-email/drafts/{q['id']}/queue").status_code == 409
    sent = w.client.post(f"/meeting-email/drafts/{q['id']}/resolve", json={"delivered": True}).json()
    assert sent["status"] == "sent"
    # the other choice: it did not arrive, send again: a fresh review, approval and Message-ID
    w2 = W()
    q2 = w2.ready()
    w2.dispatch(send=lost_answer)
    reopened = w2.client.post(f"/meeting-email/drafts/{q2['id']}/resolve", json={"delivered": False}).json()
    assert reopened["status"] == "ready_for_review" and reopened["approved_hash"] is None and reopened["message_id"] is None and reopened["attempts"] == 0
    assert w2.client.post(f"/meeting-email/drafts/{q2['id']}/resolve", json={"delivered": True}).status_code == 409  # only an unknown delivery can be settled


def test_an_unexpected_error_during_a_send_is_treated_as_ambiguous_not_retried():
    w = W()
    q = w.ready()

    async def boom(draft):
        raise RuntimeError("bug")

    w.dispatch(send=boom)
    assert w.draft(q["id"])["status"] == "unknown_delivery"


def test_a_worker_restart_mid_send_leaves_it_unknown_and_never_sends_it_again():
    w = W()
    q = w.ready()
    claimed = asyncio.run(w.emails.claim_due(datetime.now(UTC) + timedelta(minutes=11)))  # the old process claimed it and died before recording an outcome
    assert claimed.status == DraftStatus.SENDING and claimed.attempts == 1
    assert asyncio.run(dispatch_due_drafts(w.emails, send_fn=w.send, now=datetime.now(UTC) + timedelta(minutes=12))) == 0  # a SENDING draft is not due
    assert asyncio.run(recover_interrupted(w.emails, older_than_seconds=None)) == 1  # what the loop does at start
    assert w.draft(q["id"])["status"] == "unknown_delivery" and w.sent == []
    assert asyncio.run(recover_interrupted(w.emails)) == 0
    # a send that is merely slow (claimed moments ago) is left alone by the periodic check
    w3 = W()
    q3 = w3.ready()
    asyncio.run(w3.emails.claim_due(datetime.now(UTC) + timedelta(minutes=11)))
    assert asyncio.run(recover_interrupted(w3.emails, now=datetime.now(UTC), older_than_seconds=300)) == 0 and w3.draft(q3["id"])["status"] == "sending"


def test_concurrent_dispatch_workers_send_a_message_once():
    w = W()
    w.ready()
    started = asyncio.Event()

    async def slow(draft):
        started.set()
        await asyncio.sleep(0.05)
        w.sent.append((draft, []))
        return "ok"

    async def both():
        now = datetime.now(UTC) + timedelta(minutes=11)
        return await asyncio.gather(*(dispatch_due_drafts(w.emails, send_fn=slow, now=now) for _ in range(4)))

    assert sum(asyncio.run(both())) == 1 and len(w.sent) == 1


# ---- consent, authentication and origin ---------------------------------------------------------------------------------------------------------

def test_the_core_routes_refuse_a_caller_without_the_service_token():
    w = W()
    d = w.prepare(to=["a@example.org"])
    bare = TestClient(w.app)
    for method, path in [("get", "/meeting-email/config"), ("get", "/meeting-email/sender"), ("get", "/meeting-email/drafts"), ("get", f"/meeting-email/drafts/{d['id']}"),
                         ("post", f"/meeting-email/drafts/{d['id']}/queue"), ("get", f"/meeting-email/drafts/{d['id']}/attachments/x.pdf"), ("post", f"/meetings/{w.meeting_id}/email/prepare")]:
        assert getattr(bare, method)(path).status_code in (401, 403), path
    assert bare.post(f"/meeting-email/drafts/{d['id']}/approve", json={"package_hash": d["package_hash"], "confirmation": "SEND"}).status_code in (401, 403)


def test_voice_can_never_approve_queue_or_settle_a_meeting_email_at_the_service_layer():
    w = W()
    d = w.prepare(to=["a@example.org"])
    for call in (lambda: w.service.approve(d["id"], package_hash=d["package_hash"], confirmation="SEND", modality=InputModality.VOICE),
                 lambda: w.service.queue(d["id"], modality=InputModality.VOICE), lambda: w.service.resolve(d["id"], delivered=True, modality=InputModality.VOICE)):
        with pytest.raises(VoiceConfirmationNotAllowedError):
            asyncio.run(call())
    assert w.draft(d["id"])["status"] == "ready_for_review"


def test_a_chat_or_spoken_turn_cannot_approve_queue_or_send_a_meeting_package_even_when_it_names_it():
    w = W()
    q = w.ready()
    turn = {"session_id": "s1", "conversation_id": "c1", "channel": "web"}
    for text in ("send draft minutes", "send draft Meeting minutes: Weekly sync", "approve draft minutes", "send it"):
        for modality in ("text", "voice"):
            reply = w.client.post("/conversation", json={**turn, "text": text, "input_modality": modality}).json()["reply"].lower()
            assert "queued" not in reply
    assert w.draft(q["id"])["status"] == "queued" and w.sent == []
    d = w.prepare(to=["a@example.org"])
    approve = w.client.post("/conversation", json={**turn, "text": "approve draft minutes", "input_modality": "text"})
    assert w.draft(d["id"])["status"] == "ready_for_review", approve.text
    # cancelling is the safe direction and stays available by chat
    assert w.dispatch(minutes=1) == 0


def test_the_hub_audit_trail_records_who_did_what_without_content_or_credentials():
    w = W()
    q = w.ready()
    w.dispatch()
    events = w.draft(q["id"])["events"]
    assert [e["event"] for e in events][:3] == ["prepared", "approved", "queued"]
    text = str(events)
    assert "app-password-1" not in text and "SECRET-TRANSCRIPT-LINE" not in text and "Priya Shah proposed" not in text
    assert events[1]["detail"]["attachment_hashes"] and events[1]["detail"]["recipients"] == ["colleague@example.org"]


# ---- the dedicated sender ------------------------------------------------------------------------------------------------------------------------

def test_sending_is_off_by_default_and_enabling_needs_a_verified_connection():
    w = W(with_sender=False)
    assert w.client.get("/meeting-email/sender").json()["enabled"] is False
    r = w.client.post(f"/meetings/{w.meeting_id}/email/prepare", json={})
    assert r.status_code == 409 and code(r) == "no_sender"
    put = w.client.put("/meeting-email/sender", json={"host": "smtp.example.test", "from_address": SENDER, "username": SENDER, "password": "pw-1"})
    assert put.status_code == 200 and put.json()["enabled"] is False and put.json()["has_credential"] is True
    enable = w.client.put("/meeting-email/sender/enabled", json={"enabled": True})
    assert enable.status_code == 409 and code(enable) == "not_verified"


def test_the_credential_is_write_only_and_never_appears_in_any_response_or_event():
    w = W(with_sender=False)
    w.client.put("/meeting-email/sender", json={"host": "smtp.example.test", "from_address": SENDER, "username": SENDER, "password": "TOP-SECRET-APP-PASSWORD"})
    seen = [w.client.get("/meeting-email/sender").text, w.client.get("/meeting-email/config").text, str(w.client.get("/meeting-email/sender").json())]
    assert all("TOP-SECRET-APP-PASSWORD" not in s for s in seen)
    assert "password" not in w.client.get("/meeting-email/sender").json() and "secret_ref" not in w.client.get("/meeting-email/sender").json()
    assert w.client.put("/meeting-email/sender", json={"host": "h", "from_address": SENDER, "password": "x", "surprise": 1}).status_code == 422  # unknown fields are refused


@pytest.mark.parametrize("body, fragment", [
    ({"host": "smtp.example.test", "from_address": SENDER, "username": SENDER, "password": "x", "security": "none"}, "STARTTLS"),  # credentials never cross an unencrypted connection
    ({"host": "smtp.example.test", "from_address": SENDER, "username": SENDER}, "both a username and a credential"),
    ({"host": "smtp.example.test", "from_address": "not-an-address"}, "sender address"),
    ({"host": "smtp.gmail.com", "from_address": SENDER, "username": "other@gmail.com", "password": "x"}, "Gmail"),  # Gmail must send as the account it signs in with
    ({"host": "", "from_address": SENDER}, "host"),
])
def test_unsafe_sender_settings_are_refused(body, fragment):
    w = W(with_sender=False)
    r = w.client.put("/meeting-email/sender", json=body)
    assert r.status_code == 422 and fragment in r.json()["detail"]["message"]


def test_changing_the_sender_or_rotating_the_credential_switches_sending_off_until_verified_again_and_disconnect_removes_everything():
    w = W()
    assert w.client.get("/meeting-email/sender").json()["enabled"] is True
    rotated = w.client.put("/meeting-email/sender", json={"host": "smtp.example.test", "from_address": SENDER, "username": SENDER, "password": "new-password"}).json()
    assert rotated["enabled"] is False and rotated["verified_ok"] is None  # a new credential must be verified and enabled on purpose
    assert asyncio.run(w.sender_store.password()) == "new-password"
    unchanged = w.client.put("/meeting-email/sender", json={"host": "smtp.example.test", "from_address": SENDER, "username": SENDER}).json()
    assert unchanged["has_credential"] is True  # saving without a password keeps the stored one
    asyncio.run(w.sender_store.record_verification(True, "ok"))
    asyncio.run(w.sender_store.set_enabled(True))
    gone = w.client.delete("/meeting-email/sender").json()
    assert gone["configured"] is False and gone["enabled"] is False and gone["has_credential"] is False and asyncio.run(w.sender_store.password()) is None


def test_a_changed_sender_identity_after_approval_stops_the_send():
    w = W()
    q = w.ready()
    asyncio.run(w.sender_store.save(SenderSettings(host="smtp.example.test", from_address="someone.else@example.test", username="someone.else@example.test"), password="pw"))
    asyncio.run(w.sender_store.record_verification(True, "ok"))
    asyncio.run(w.sender_store.set_enabled(True))
    real = MailSender(w.sender_store)
    assert asyncio.run(dispatch_due_drafts(w.emails, send_fn=real, now=datetime.now(UTC) + timedelta(minutes=11))) == 0
    final = w.draft(q["id"])
    assert final["status"] == "failed" and "identity changed" in final["last_error"]


def test_a_meeting_package_never_falls_back_to_the_deployment_environment_sender(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    w = W(with_sender=False)
    draft = EmailDraft(to="a@example.org", subject="s", body="b", kind=MEETING_MINUTES_KIND, recipients=Recipients(to=["a@example.org"]))
    with pytest.raises(SendRefused, match="no outbound sender"):
        asyncio.run(MailSender(w.sender_store)(draft))


# ---- the flag and the older conversational drafts ----------------------------------------------------------------------------------------------

def test_with_the_flag_off_the_routes_and_the_service_do_not_exist(monkeypatch):
    monkeypatch.delenv("MEETING_EMAIL_ENABLED", raising=False)
    app = create_app(calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
                     memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
                     llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(),
                     search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False, accounts_service_token=TOKEN)
    client = TestClient(app, headers=HEADERS)
    assert app.state.meeting_email is None
    for path in ("/meeting-email/config", "/meeting-email/sender", "/meeting-email/drafts", "/meeting-email/groups"):
        assert client.get(path).status_code == 404
    assert client.post("/meetings/x/email/prepare", json={}).status_code == 404


def test_older_text_drafts_keep_their_original_one_recipient_flow_and_use_the_same_loop():
    w = W()
    store = w.emails

    async def go():
        draft = await store.create_draft(to="bob@example.org", subject="Hi", body="Hello")
        approved = await store.approve_draft(draft.id)
        assert approved.status == DraftStatus.APPROVED and approved.kind == "text" and approved.package_hash is None
        await store.queue_draft(draft.id, dispatch_at=datetime.now(UTC) - timedelta(seconds=1))
        return await dispatch_due_drafts(store, send_fn=w.send)

    assert asyncio.run(go()) == 1 and w.sent[0][0].to == "bob@example.org" and w.sent[0][1] == []


def test_distribution_errors_carry_a_status_and_a_stable_code():
    err = DistributionError(409, "text", "bad_state")
    assert (err.status, err.detail, err.code) == (409, "text", "bad_state")
    with pytest.raises(SenderConfigError):
        asyncio.run(InMemoryMailSenderStore().set_enabled(True))


# ---- conversation: a draft may be requested, never approved or sent --------------------------------------------------------------------------------

def _say(w, text, modality="text"):
    return w.client.post("/conversation", json={"session_id": "s1", "conversation_id": "c1", "channel": "web", "text": text, "input_modality": modality}).json()["reply"]


@pytest.mark.parametrize("modality", ["text", "voice"])
@pytest.mark.parametrize("phrase", ["prepare an email with the minutes of Weekly sync", "Draft the minutes email for the weekly sync meeting.", "please prepare the email with the summary and minutes of weekly sync"])
def test_a_spoken_or_typed_request_can_prepare_a_draft_but_it_has_no_recipients_and_nothing_is_sent(phrase, modality):
    w = W()
    reply = _say(w, phrase, modality)
    assert "prepared a draft" in reply and "nothing has been sent" in reply and "can't approve or send it by voice or chat" in reply
    [draft] = asyncio.run(w.emails.list_drafts(kind=MEETING_MINUTES_KIND))
    assert draft.status == DraftStatus.READY_FOR_REVIEW and draft.recipients.everyone() == [] and draft.approved_hash is None
    assert w.sent == [] and w.dispatch() == 0
    assert w.client.get("/meeting-email/drafts").json()[0]["status"] == "ready_for_review"


def test_a_draft_request_that_matches_no_meeting_or_several_creates_nothing_and_says_why():
    w = W()
    assert "couldn't find a finished meeting" in _say(w, "prepare an email with the minutes of Budget review")
    other = asyncio.run(w.meetings.create_meeting(title="Weekly sync review", audio=b"x", source_filename="b.wav", content_type="audio/wav"))
    w.meetings._touch(other, status=MeetingJobStatus.COMPLETE, transcript_segments=SEGMENTS)
    assert "2 meetings match" in _say(w, "prepare an email with the minutes of Weekly sync")
    assert asyncio.run(w.emails.list_drafts(kind=MEETING_MINUTES_KIND)) == []


def test_a_draft_request_that_the_meeting_cannot_support_reports_the_reason_and_nothing_is_created():
    w = W()
    asyncio.run(w.meetings.set_speaker_names(w.meeting_id, {"SPEAKER_00": "Someone Else"}))  # the outputs no longer match the names
    reply = _say(w, "prepare an email with the minutes of Weekly sync")
    assert "couldn't prepare that draft" in reply and "speaker names changed" in reply and "Nothing has been sent" in reply
    assert asyncio.run(w.emails.list_drafts(kind=MEETING_MINUTES_KIND)) == []


def test_the_request_is_not_recognised_when_the_feature_is_off_and_sending_wording_is_never_a_draft_request():
    w = W()
    for text in ("send the minutes email for weekly sync", "approve the minutes email for weekly sync", "prepare and send an email with the minutes of weekly sync"):
        reply = _say(w, text, "voice")
        assert "prepared a draft" not in reply
    assert asyncio.run(w.emails.list_drafts(kind=MEETING_MINUTES_KIND)) == [] and w.sent == []


# ---- the sender test: one fixed message to the address typed in Settings ----------------------------------------------------------------------------

def test_a_test_email_goes_to_the_typed_address_with_fixed_text_no_attachment_and_no_meeting_content():
    w = W()
    r = w.client.post("/meeting-email/sender/test", json={"to": "Owner.Test@Example.org"})
    assert r.status_code == 200 and r.json()["status"] == "sent" and r.json()["to"] == "owner.test@example.org" and r.json()["provider_response"] == "2.0.0 OK queued"
    [(draft, blobs)] = w.sent
    assert draft.kind == "sender_test" and draft.subject == "Reachy test email" and draft.sender == SENDER and blobs == []
    assert draft.recipients.everyone() == ["owner.test@example.org"] and draft.attachments == []
    assert "test message from Reachy" in draft.body and "no meeting content" in draft.body
    assert "Weekly sync" not in draft.body and "Priya" not in draft.body and "SECRET-TRANSCRIPT-LINE" not in draft.body  # nothing from any meeting
    assert [e.event for e in asyncio.run(w.emails.list_events(draft.id))] == ["prepared", "approved", "queued", "sending", "sent"]  # recorded like every other message
    assert w.client.get("/meeting-email/drafts").json() == []  # it is not a meeting message, and it cannot be opened, edited or approved as one
    assert w.client.get(f"/meeting-email/drafts/{draft.id}").status_code == 404
    assert w.dispatch(minutes=30) == 0 and len(w.sent) == 1  # a later pass never sends it again


@pytest.mark.parametrize("bad", ["", "nobody", "a@b", "a b@example.org", "a@example.org\r\nBcc: evil@example.net", "Name <a@example.org>", "a@example.org, b@example.org"])
def test_a_test_email_needs_exactly_one_plain_valid_address(bad):
    w = W()
    r = w.client.post("/meeting-email/sender/test", json={"to": bad})
    assert r.status_code == 422 and code(r) == "bad_recipient"
    assert w.sent == [] and asyncio.run(w.emails.list_drafts(kind="sender_test")) == []
    assert w.client.post("/meeting-email/sender/test", json={"to": "a@example.org", "also": "b@example.org"}).status_code == 422  # a second recipient cannot be smuggled in


def test_a_test_email_needs_a_configured_and_switched_on_sender_so_off_really_means_off():
    off = W(enabled=False)
    r = off.client.post("/meeting-email/sender/test", json={"to": "a@example.org"})
    assert r.status_code == 409 and code(r) == "sending_off" and off.sent == [] and asyncio.run(off.emails.list_drafts(kind="sender_test")) == []
    none = W(with_sender=False)
    r = none.client.post("/meeting-email/sender/test", json={"to": "a@example.org"})
    assert r.status_code == 409 and code(r) == "no_sender" and none.sent == []


def test_test_emails_are_rate_limited_to_a_few_an_hour_with_a_short_gap():
    w = W()
    clock = {"now": datetime.now(UTC)}
    w.service.clock = lambda: clock["now"]
    assert w.client.post("/meeting-email/sender/test", json={"to": "a@example.org"}).status_code == 200
    again = w.client.post("/meeting-email/sender/test", json={"to": "a@example.org"})
    assert again.status_code == 409 and code(again) == "rate_limited"  # too soon after the last one
    for _ in range(4):
        clock["now"] += timedelta(seconds=20)
        assert w.client.post("/meeting-email/sender/test", json={"to": "a@example.org"}).status_code == 200
    clock["now"] += timedelta(seconds=20)
    sixth = w.client.post("/meeting-email/sender/test", json={"to": "a@example.org"})
    assert sixth.status_code == 409 and code(sixth) == "rate_limited" and len(w.sent) == 5
    clock["now"] += timedelta(hours=1)  # the window moves on
    assert w.client.post("/meeting-email/sender/test", json={"to": "a@example.org"}).status_code == 200


def test_a_failed_or_ambiguous_test_reports_what_happened_and_is_never_retried():
    w = W()

    async def refused(draft):
        raise SendRefused("authentication failed: 535")

    w.service._send_fn = refused
    r = w.client.post("/meeting-email/sender/test", json={"to": "a@example.org"}).json()
    assert r["status"] == "failed" and "authentication failed" in r["error"]
    clock = datetime.now(UTC)
    w.service.clock = lambda: clock + timedelta(minutes=5)

    async def lost(draft):
        raise SendUnknown("no final answer after sending: timeout")

    w.service._send_fn = lost
    r = w.client.post("/meeting-email/sender/test", json={"to": "a@example.org"}).json()
    assert r["status"] == "unknown_delivery" and "no final answer" in r["error"]
    assert w.dispatch(minutes=120) == 0 and w.sent == []  # neither is picked up again by the loop


def test_a_test_email_is_text_only_and_refuses_voice_at_the_service_layer_and_needs_the_service_token():
    w = W()
    with pytest.raises(VoiceConfirmationNotAllowedError):
        asyncio.run(w.service.send_test("a@example.org", modality=InputModality.VOICE))
    assert w.sent == [] and asyncio.run(w.emails.list_drafts(kind="sender_test")) == []
    assert TestClient(w.app).post("/meeting-email/sender/test", json={"to": "a@example.org"}).status_code in (401, 403)
    for text in ("send a test email to a@example.org", "send a test email"):
        for modality in ("text", "voice"):
            _say(w, text, modality)
    assert w.sent == [] and asyncio.run(w.emails.list_drafts(kind="sender_test")) == []  # nothing in conversation reaches it


def test_a_test_email_never_falls_back_to_the_deployment_environment_sender(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    w = W(with_sender=False)
    draft = EmailDraft(to="a@example.org", subject="Reachy test email", body="x", kind="sender_test", recipients=Recipients(to=["a@example.org"]))
    with pytest.raises(SendRefused, match="no outbound sender"):
        asyncio.run(MailSender(w.sender_store)(draft))


# ---- sign-in mechanism (found on the first real Gmail attempt) ---------------------------------------------------------------------------------------

class _AuthClient:
    """What the sender sees of the SMTP client after TLS: the mechanisms the server advertises and the calls it makes."""

    def __init__(self, advertised: str | None):
        self.esmtp_extensions = {"auth": advertised} if advertised is not None else {}
        self.calls: list[tuple] = []

    async def auth_plain(self, user, password):
        self.calls.append(("plain", user))

    async def auth_login(self, user, password):
        self.calls.append(("login", user))

    async def login(self, user, password):  # the library's generic method must never be used: it tries other mechanisms first and Gmail drops the connection
        raise AssertionError("login() must not be called")


@pytest.mark.parametrize("advertised, expected", [("LOGIN PLAIN XOAUTH2 PLAIN-CLIENTTOKEN OAUTHBEARER", "plain"), ("login plain", "plain"), ("LOGIN", "login"), ("CRAM-MD5 LOGIN", "login")])
def test_the_sender_signs_in_with_plain_else_login_from_what_the_server_advertises_and_never_the_generic_login(advertised, expected):
    client = _AuthClient(advertised)
    asyncio.run(MailSender._sign_in(client, "user@example.test", "pw"))
    assert client.calls == [(expected, "user@example.test")]


@pytest.mark.parametrize("advertised", ["CRAM-MD5 XOAUTH2", "", None])
def test_a_server_with_no_password_sign_in_is_refused_with_a_clear_reason_and_nothing_is_attempted(advertised):
    client = _AuthClient(advertised)
    with pytest.raises(SendRefused, match="does not offer password sign-in"):
        asyncio.run(MailSender._sign_in(client, "user@example.test", "pw"))
    assert client.calls == []
