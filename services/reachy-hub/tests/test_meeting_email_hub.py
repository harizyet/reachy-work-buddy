"""Phase 55 through the hub: the owner-only proxy (owner session plus CSRF, no bearer path, fixed errors), the flag-off behaviour, the write-only credential, and the whole chain
hub -> real core app with a recording send function. In-process; no mail server, nothing is deployed."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from companion_core.app import create_app as create_core_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.sender_config import InMemoryMailSenderStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.email.workflow import dispatch_due_drafts
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meeting_distribution.groups import InMemoryGroupStore
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
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.user_store import InMemoryUserStore

CSRF = {"X-Reachy-CSRF": "1"}
BEARER = {"Authorization": "Bearer test-token"}
SENDER = "reachy.minutes@example.test"
PASSWORD = "HUB-TEST-APP-PASSWORD"


def build(*, enabled=True):
    meetings, emails, senders = InMemoryMeetingStore(), InMemoryEmailStore(), InMemoryMailSenderStore()
    sent = []

    async def send(draft):
        sent.append((draft, list(draft.attachment_blobs)))
        return "250 ok"

    async def seed():
        m = await meetings.create_meeting(title="Weekly sync", audio=b"x", source_filename="a.wav", content_type="audio/wav", started_at=datetime(2026, 10, 14, 6, 0, tzinfo=UTC))
        names = {"SPEAKER_00": "Priya Shah"}
        meetings._touch(m, status=MeetingJobStatus.COMPLETE, transcript_segments=[{"start": 0.0, "end": 3.0, "text": "hello"}], speaker_names=names,
                        summary=MeetingOutput(text="Priya Shah proposed shipping on Friday.", tier="local", speaker_basis=speaker_basis(names)),
                        minutes=MeetingOutput(text="Topics discussed\n- Release", tier="local", speaker_basis=speaker_basis(names)))
        return m.id

    meeting_id = asyncio.run(seed())
    core = create_core_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=meetings, run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=emails, email_send_fn=send, confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, meeting_email_enabled=enabled, mail_sender_store=senders, recipient_group_store=InMemoryGroupStore(), email_send_delay_seconds=600)
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    hub = TestClient(create_app(
        user_store=users, registry=InMemoryRobotRegistry(), session_store=InMemorySessionStore(), audit_log=InMemoryAuditLog(), notification_queue=InMemoryNotificationQueue(),
        run_heartbeat_task=False, run_telegram_poll_task=False, session_secret_key="test-session-secret", remote_ui_token="test-token",
        companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core))))
    return hub, core, emails, senders, sent, meeting_id


def login(client):
    assert client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF).status_code == 200


ROUTES = [
    ("get", "/meeting-email/config", None), ("get", "/meeting-email/sender", None), ("put", "/meeting-email/sender", {"host": "h", "from_address": SENDER}),
    ("post", "/meeting-email/sender/verify", {}), ("post", "/meeting-email/sender/test", {"to": "a@example.org"}), ("put", "/meeting-email/sender/enabled", {"enabled": True}), ("delete", "/meeting-email/sender", None),
    ("get", "/meeting-email/groups", None), ("post", "/meeting-email/groups", {"name": "g", "addresses": ["a@example.org"]}), ("put", "/meeting-email/groups/abc", {"name": "g", "addresses": ["a@example.org"]}),
    ("delete", "/meeting-email/groups/abc", None), ("get", "/meeting-email/drafts", None), ("get", "/meeting-email/drafts/abc", None), ("put", "/meeting-email/drafts/abc", {"subject": "x"}),
    ("post", "/meeting-email/drafts/abc/approve", {"package_hash": "0" * 64, "confirmation": "SEND"}), ("post", "/meeting-email/drafts/abc/queue", {}), ("post", "/meeting-email/drafts/abc/cancel-send", {}),
    ("post", "/meeting-email/drafts/abc/discard", {}), ("post", "/meeting-email/drafts/abc/resolve", {"delivered": True}), ("get", "/meeting-email/drafts/abc/attachments/m.pdf", None),
    ("post", "/meetings/abc/email/prepare", {}), ("get", "/meetings/abc/email/suggestions", None),
]
CHANGES = [r for r in ROUTES if r[0] != "get"]


def call(client, method, path, body, headers=None):
    return getattr(client, method)(path, headers=headers or {}, **({"json": body} if body is not None else {}))


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_no_login_and_a_bearer_token_alone_are_refused_on_every_route(method, path, body):
    hub, _core, emails, _senders, sent, meeting_id = build()
    with hub:
        assert call(hub, method, path.replace("abc", meeting_id), body, CSRF).status_code == 401
        assert call(hub, method, path.replace("abc", meeting_id), body, {**BEARER, **CSRF}).status_code == 401  # a robot-control credential must not approve or send mail
    assert asyncio.run(emails.list_drafts()) == [] and sent == []


@pytest.mark.parametrize(("method", "path", "body"), CHANGES)
def test_every_change_needs_the_csrf_header(method, path, body):
    hub, _core, _emails, _senders, sent, meeting_id = build()
    with hub:
        login(hub)
        assert call(hub, method, path.replace("abc", meeting_id), body).status_code == 403
    assert sent == []


def test_with_the_flag_off_the_config_says_so_and_the_rest_do_not_exist():
    hub, _core, _emails, _senders, _sent, meeting_id = build(enabled=False)
    with hub:
        login(hub)
        assert hub.get("/meeting-email/config").json() == {"enabled": False}
        assert hub.get("/meeting-email/drafts").status_code == 404
        assert hub.post(f"/meetings/{meeting_id}/email/prepare", json={}, headers=CSRF).status_code == 404


def test_the_whole_flow_through_the_hub_keeps_the_credential_out_of_every_response_and_sends_the_approved_package_once():
    hub, _core, emails, senders, sent, meeting_id = build()
    seen = []
    with hub:
        login(hub)

        def ok(response, status=200):
            seen.append(response.text)
            assert response.status_code == status, response.text
            return response.json()

        assert ok(hub.get("/meeting-email/config"))["enabled"] is True
        sender = ok(hub.put("/meeting-email/sender", headers=CSRF, json={"host": "smtp.example.test", "from_address": SENDER, "username": SENDER, "owner_name": "Hariz", "password": PASSWORD}))
        assert sender["has_credential"] is True and sender["enabled"] is False
        assert ok(hub.put("/meeting-email/sender/enabled", headers=CSRF, json={"enabled": True}), 409)["detail"]["code"] == "not_verified"
        asyncio.run(senders.record_verification(True, "connected"))  # the live verification is covered against Mailpit; here only the proxy matters
        assert ok(hub.put("/meeting-email/sender/enabled", headers=CSRF, json={"enabled": True}))["enabled"] is True

        # the sender test: one fixed message to the typed address, through the proxy, with core enforcing the rules
        bad = hub.post("/meeting-email/sender/test", headers=CSRF, json={"to": "not an address"})
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_recipient"
        assert hub.post("/meeting-email/sender/test", headers=CSRF, json={"to": "a@example.org", "also": "b@example.org"}).status_code == 422
        tested = ok(hub.post("/meeting-email/sender/test", headers=CSRF, json={"to": "Owner.Test@Example.org"}))
        assert tested["status"] == "sent" and tested["to"] == "owner.test@example.org" and tested["provider_response"] == "250 ok"
        assert sent[-1][0].subject == "Reachy test email" and sent[-1][0].kind == "sender_test" and sent[-1][1] == []
        sent.clear()

        draft = ok(hub.post(f"/meetings/{meeting_id}/email/prepare", headers=CSRF, json={"to": ["Colleague@Example.org"], "cc": ["boss@example.org"]}))
        assert draft["status"] == "ready_for_review" and draft["recipients"]["to"] == ["colleague@example.org"] and "Priya Shah proposed" in draft["body"]
        edited = ok(hub.put(f"/meeting-email/drafts/{draft['id']}", headers=CSRF, json={"subject": "Minutes of the weekly sync"}))
        wrong = hub.post(f"/meeting-email/drafts/{draft['id']}/approve", headers=CSRF, json={"package_hash": draft["package_hash"], "confirmation": "SEND"})
        assert wrong.status_code == 409 and wrong.json()["detail"] == {"message": "The message changed since you reviewed it. Review it again.", "code": "changed"}  # the hash of the earlier version
        no_word = hub.post(f"/meeting-email/drafts/{draft['id']}/approve", headers=CSRF, json={"package_hash": edited["package_hash"], "confirmation": "yes"})
        assert no_word.status_code == 422 and no_word.json()["detail"]["code"] == "confirmation_required"
        assert hub.post(f"/meeting-email/drafts/{draft['id']}/approve", headers=CSRF, json={"package_hash": edited["package_hash"], "confirmation": "SEND", "extra": 1}).status_code == 422  # unknown fields refused
        approved = ok(hub.post(f"/meeting-email/drafts/{draft['id']}/approve", headers=CSRF, json={"package_hash": edited["package_hash"], "confirmation": "SEND"}))
        assert approved["status"] == "approved" and approved["approved_hash"] == edited["package_hash"]
        queued = ok(hub.post(f"/meeting-email/drafts/{draft['id']}/queue", headers=CSRF))
        assert queued["status"] == "queued"

        pdf = hub.get(f"/meeting-email/drafts/{draft['id']}/attachments/{queued['attachments'][0]['name']}")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-") and pdf.headers["cache-control"] == "no-store" and pdf.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in pdf.headers["content-security-policy"] and hub.get(f"/meeting-email/drafts/{draft['id']}/attachments/missing.pdf").status_code == 404

        assert asyncio.run(dispatch_due_drafts(emails, send_fn=lambda d: _record(sent, d), now=datetime.now(UTC) + timedelta(minutes=11))) == 1
        final = ok(hub.get(f"/meeting-email/drafts/{draft['id']}"))
        assert final["status"] == "sent" and [e["event"] for e in final["events"]] == ["prepared", "edited", "approved", "queued", "sending", "sent"]
        assert len(sent) == 1 and sent[0][0].subject == "Minutes of the weekly sync"
        assert [d["id"] for d in ok(hub.get(f"/meeting-email/drafts?meeting_id={meeting_id}"))] == [draft["id"]]
        assert ok(hub.get("/meeting-email/drafts?meeting_id=nobody")) == []
        gone = ok(hub.delete("/meeting-email/sender", headers=CSRF))
        assert gone["configured"] is False and gone["has_credential"] is False
    assert all(PASSWORD not in text for text in seen)  # the credential never came back, in any response


async def _record(sent, draft):
    sent.append((draft, list(draft.attachment_blobs)))
    return "250 ok"


def test_an_id_that_is_not_a_plain_identifier_never_reaches_core():
    hub, _core, _emails, _senders, _sent, _meeting_id = build()
    with hub:
        login(hub)
        for bad in ("a b", "a%2Fb", "x" * 80):
            assert hub.get(f"/meeting-email/drafts/{bad}").status_code in (404, 422)
        assert hub.get("/meeting-email/drafts/ok/attachments/..%2Fetc").status_code in (404, 422)
