"""Phase 55 (ADR 0039): the real sender against a real SMTP server. Opt-in: set MAILPIT_TEST=1 (needs Docker and the `axllent/mailpit` image). The fixture starts a throwaway Mailpit with
STARTTLS required, a self-signed certificate and one SMTP account, on private loopback ports, and removes it afterwards. A small in-test SMTP server produces the outcomes Mailpit cannot:
a message accepted but never acknowledged, a refused recipient, a deferral. Nothing here touches a real mailbox or a real credential."""

import asyncio
import hashlib
import ipaddress
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
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
)
from companion_core.email.sender_config import InMemoryMailSenderStore, SenderSettings
from companion_core.email.store import InMemoryEmailStore
from companion_core.email.workflow import dispatch_due_drafts, run_dispatch_loop
from companion_core.meeting_distribution.groups import InMemoryGroupStore
from companion_core.meeting_distribution.service import MeetingEmailService
from companion_core.meetings.models import (
    MeetingJobStatus,
    MeetingOutput,
    speaker_basis,
)
from companion_core.meetings.store import InMemoryMeetingStore
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

pytestmark = pytest.mark.skipif(os.environ.get("MAILPIT_TEST") != "1" or shutil.which("docker") is None, reason="needs MAILPIT_TEST=1 and Docker")

USER, PASSWORD = "reachy.minutes@example.test", "test-app-password-9x7q"
INBOX = "owner.test.inbox@example.org"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Mailpit:
    def __init__(self, workdir: Path) -> None:
        now = datetime.now(UTC)
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "reachy test CA")])
        ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=2))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False, data_encipherment=False,
                                           key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
              .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
              .sign(ca_key, hashes.SHA256()))
        key = ec.generate_private_key(ec.SECP256R1())
        cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])).issuer_name(ca_name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=2))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.DNSName("localhost")]), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .sign(ca_key, hashes.SHA256()))
        self.cert = workdir / "ca.pem"  # what the client trusts
        self.cert.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        (workdir / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (workdir / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (workdir / "auth.txt").write_text(f"{USER}:{PASSWORD}\n")
        for f in workdir.iterdir():
            f.chmod(0o644)
        workdir.chmod(0o755)
        self.smtp, self.api = free_port(), free_port()
        self.name = f"mailpit-test-{os.getpid()}-{self.smtp}"
        subprocess.run(["docker", "run", "-d", "--name", self.name, "-p", f"127.0.0.1:{self.smtp}:1025", "-p", f"127.0.0.1:{self.api}:8025", "-v", f"{workdir}:/c:ro",
                        "-e", "MP_SMTP_AUTH_FILE=/c/auth.txt", "-e", "MP_SMTP_TLS_CERT=/c/cert.pem", "-e", "MP_SMTP_TLS_KEY=/c/key.pem", "-e", "MP_SMTP_REQUIRE_STARTTLS=true",
                        "axllent/mailpit"], check=True, capture_output=True)
        for _ in range(60):
            try:
                self.get("/api/v1/info")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        else:
            raise RuntimeError("mailpit did not start")
        self.tls = ssl.create_default_context(cafile=str(self.cert))

    def get(self, path: str) -> bytes:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.api}{path}", timeout=10) as r:
            return r.read()

    def messages(self) -> list[dict]:
        return json.loads(self.get("/api/v1/messages"))["messages"]

    def message(self, message_id: str) -> dict:
        return json.loads(self.get(f"/api/v1/message/{message_id}"))

    def clear(self) -> None:
        urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{self.api}/api/v1/messages", method="DELETE"), timeout=10).read()

    def stop(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, check=False)


@pytest.fixture(scope="module")
def mailpit():
    workdir = Path(tempfile.mkdtemp(prefix="mailpit-test-"))
    server = Mailpit(workdir)
    try:
        yield server
    finally:
        server.stop()
        shutil.rmtree(workdir, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean(mailpit):
    mailpit.clear()
    yield


def settings(mailpit, **over) -> SenderSettings:
    base = {"host": "127.0.0.1", "port": mailpit.smtp, "security": "starttls", "from_address": USER, "username": USER}
    base.update(over)
    return SenderSettings(**base)


async def sender_store(mailpit, *, password=PASSWORD, enabled=True, **over) -> InMemoryMailSenderStore:
    store = InMemoryMailSenderStore()
    await store.save(settings(mailpit, **over), password=password)
    await store.record_verification(True, "ok")
    if enabled:
        await store.set_enabled(True)
    return store


# ---- a tiny SMTP server for outcomes Mailpit cannot produce -------------------------------------------------------------------------------------

class FakeSmtp:
    """mode: 'hang' (accept the message, never answer), 'rcpt_refused', 'defer' (451 after DATA), 'accept'."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.received: list[str] = []
        self.rcpts: list[str] = []
        self.server: asyncio.AbstractServer | None = None
        self.port = 0

    async def start(self):
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    async def _client(self, reader, writer):
        async def say(line):
            writer.write(line.encode() + b"\r\n")
            await writer.drain()

        await say("220 fake ESMTP")
        try:
            while line := await reader.readline():
                cmd = line.decode().strip().upper()
                if cmd.startswith(("EHLO", "HELO")):
                    await say("250-fake")
                    await say("250 8BITMIME")
                elif cmd.startswith("MAIL"):
                    await say("250 ok")
                elif cmd.startswith("RCPT"):
                    self.rcpts.append(cmd.split("<", 1)[-1].split(">", 1)[0].lower())
                    await say("550 5.1.1 no such user" if self.mode == "rcpt_refused" else "250 ok")
                elif cmd == "DATA":
                    await say("354 go ahead")
                    data = b""
                    while not data.endswith(b"\r\n.\r\n"):
                        data += await reader.readline()
                    self.received.append(data.decode(errors="replace"))
                    if self.mode == "hang":
                        await asyncio.sleep(30)  # the message is with the server; no answer ever comes
                        return
                    await say("451 4.3.0 try again later" if self.mode == "defer" else "250 2.0.0 OK queued as FAKE123")
                elif cmd == "QUIT":
                    await say("221 bye")
                    break
                else:
                    await say("250 ok")
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()


def plain(port: int) -> SenderSettings:
    return SenderSettings(host="127.0.0.1", port=port, security="none", from_address=USER, enabled=True)


async def plain_store(port: int) -> InMemoryMailSenderStore:
    store = InMemoryMailSenderStore()
    await store.save(plain(port).model_copy(update={"enabled": False}), password=None)
    await store.record_verification(True, "ok")
    await store.set_enabled(True)
    return store


def package(**over) -> EmailDraft:
    base = {"to": "a@example.org", "subject": "Meeting minutes: Weekly sync", "body": "Hello\n\nThe minutes.\n", "kind": MEETING_MINUTES_KIND, "sender": USER, "message_id": "<fixed-id@example.test>",
            "recipients": Recipients(to=["a@example.org"]), "approved_at": datetime.now(UTC), "status": DraftStatus.READY_FOR_REVIEW}
    base.update(over)
    return EmailDraft(**base)


def test_real_authentication_works_without_the_generic_login_that_gmail_drops_the_connection_on(mailpit, monkeypatch):
    import aiosmtplib

    async def forbidden(self, *args, **kwargs):
        raise AssertionError("the generic login() must not be used")

    monkeypatch.setattr(aiosmtplib.SMTP, "login", forbidden)

    async def go():
        good = await sender_store(mailpit)
        ok = await MailSender(good, allow_env=False, tls_context=mailpit.tls).verify()
        bad = await sender_store(mailpit, password="wrong-password")
        refused = await MailSender(bad, allow_env=False, tls_context=mailpit.tls).verify()
        return ok, refused

    ok, refused = asyncio.run(go())
    assert ok["ok"] is True and ok["stage"] == "authenticated"
    assert refused["ok"] is False and "authentication failed" in refused["detail"] and "wrong-password" not in refused["detail"]


# ---- connection verification ---------------------------------------------------------------------------------------------------------------------

def test_verification_connects_negotiates_tls_and_signs_in_without_sending_anything(mailpit):
    async def go():
        store = await sender_store(mailpit)
        result = await MailSender(store, allow_env=False, tls_context=mailpit.tls).verify()
        assert result["ok"] is True and result["stage"] == "authenticated" and PASSWORD not in result["detail"]

    asyncio.run(go())
    assert mailpit.messages() == []  # nothing was sent and no recipient was involved


def test_a_wrong_password_is_reported_without_echoing_it_and_nothing_is_sent(mailpit):
    async def go():
        store = await sender_store(mailpit, password="not-the-password")
        result = await MailSender(store, allow_env=False, tls_context=mailpit.tls).verify()
        assert result["ok"] is False and "authentication failed" in result["detail"] and "not-the-password" not in result["detail"]

    asyncio.run(go())
    assert mailpit.messages() == []


def test_certificate_verification_is_on_by_default_so_an_untrusted_server_is_refused(mailpit):
    async def go():
        store = await sender_store(mailpit)
        result = await MailSender(store, allow_env=False).verify()  # no test context: the real, verifying default
        assert result["ok"] is False and "could not connect" in result["detail"] and "CERTIFICATE_VERIFY_FAILED" in result["detail"].upper().replace(" ", "_") or "certificate" in result["detail"].lower()

    asyncio.run(go())


def test_credentials_are_never_sent_over_an_unencrypted_connection(mailpit):
    async def go():
        bad = await sender_store(mailpit, security="none")
        return bad

    with pytest.raises(Exception, match="STARTTLS"):
        asyncio.run(go())  # refused when the settings are saved; the sender refuses a hand-built one too
    store = InMemoryMailSenderStore()
    store._settings = settings(mailpit, security="none", enabled=True)
    store._password = PASSWORD

    async def send():
        with pytest.raises(SendRefused, match="STARTTLS"):
            await MailSender(store, tls_context=mailpit.tls)(package())

    asyncio.run(send())
    assert mailpit.messages() == []


# ---- delivery ------------------------------------------------------------------------------------------------------------------------------------

def test_a_delivered_message_has_the_approved_subject_body_attachment_and_hidden_bcc(mailpit):
    pdf = b"%PDF-1.4\n% a stand-in attachment with bytes \x00\x01\x02\xff\n%%EOF\n"
    digest = hashlib.sha256(pdf).hexdigest()

    async def go():
        store = await sender_store(mailpit)
        emails = InMemoryEmailStore()
        draft = package(recipients=Recipients(to=[INBOX], cc=["cc.person@example.org"], bcc=["hidden.person@example.org"]), to=INBOX)
        saved = await emails.create_package(draft, [("Weekly-sync-minutes.pdf", "application/pdf", pdf)])
        approved = await emails.approve_reviewed(saved.id, package_hash=saved.package_hash, message_id="<fixed-id@example.test>")
        await emails.queue_draft(saved.id, dispatch_at=datetime.now(UTC) - timedelta(seconds=1))
        sent = await dispatch_due_drafts(emails, send_fn=MailSender(store, tls_context=mailpit.tls))
        return sent, await emails.get_draft(saved.id), approved

    sent, final, approved = asyncio.run(go())
    assert sent == 1 and final.status == DraftStatus.SENT and final.provider_response and final.attempts == 1
    [summary] = mailpit.messages()
    message = mailpit.message(summary["ID"])
    assert message["Subject"] == approved.subject and message["From"]["Address"] == USER
    assert [a["Address"] for a in message["To"]] == [INBOX] and [a["Address"] for a in message["Cc"]] == ["cc.person@example.org"]
    assert [a["Address"] for a in message["Bcc"]] == ["hidden.person@example.org"]  # delivered through the envelope (Mailpit adds its own display-only Bcc line to its stored copy)
    raw = mailpit.get(f"/api/v1/message/{summary['ID']}/raw").decode()
    assert message["Text"].replace("\r\n", "\n").strip() == approved.body.strip()
    assert "Message-ID: <fixed-id@example.test>" in raw
    [attachment] = message["Attachments"]
    assert attachment["FileName"] == "Weekly-sync-minutes.pdf" and attachment["ContentType"] == "application/pdf"
    assert hashlib.sha256(mailpit.get(f"/api/v1/message/{summary['ID']}/part/{attachment['PartID']}")).hexdigest() == digest


def test_the_whole_flow_from_a_completed_meeting_to_the_owners_test_inbox_through_the_real_loop(mailpit):
    async def go():
        meetings, emails, store = InMemoryMeetingStore(), InMemoryEmailStore(), await sender_store(mailpit)
        m = await meetings.create_meeting(title="Weekly sync", audio=b"x", source_filename="a.wav", content_type="audio/wav", started_at=datetime(2026, 10, 14, 6, 0, tzinfo=UTC))
        names = {"SPEAKER_00": "Priya Shah"}
        meetings._touch(m, status=MeetingJobStatus.COMPLETE, transcript_segments=[{"start": 0, "end": 3, "text": "hello"}], speaker_names=names,
                        summary=MeetingOutput(text="Priya Shah proposed shipping on Friday.", tier="local", speaker_basis=speaker_basis(names)),
                        minutes=MeetingOutput(text="Topics discussed\n- Release", tier="local", speaker_basis=speaker_basis(names)))
        service = MeetingEmailService(emails=emails, meetings=meetings, senders=store, groups=InMemoryGroupStore(), delay_seconds=0)
        draft = await service.prepare(m.id, to=[INBOX])
        await service.approve(draft["id"], package_hash=draft["package_hash"], confirmation="send")
        await service.queue(draft["id"])
        task = asyncio.create_task(run_dispatch_loop(emails, send_fn=MailSender(store, tls_context=mailpit.tls), interval_seconds=0.1))
        try:
            for _ in range(80):
                if (await emails.get_draft(draft["id"])).status == DraftStatus.SENT:
                    break
                await asyncio.sleep(0.1)
        finally:
            task.cancel()
        return draft, await service.get(draft["id"])

    draft, final = asyncio.run(go())
    assert final["status"] == "sent" and [e["event"] for e in final["events"]] == ["prepared", "approved", "queued", "sending", "sent"]
    [summary] = mailpit.messages()
    message = mailpit.message(summary["ID"])
    assert message["Subject"] == draft["subject"] == "Meeting minutes: Weekly sync"
    assert "Priya Shah proposed shipping on Friday." in message["Text"] and "Wed 14 Oct 2026, 06:00 (UTC)" in message["Text"]
    [attachment] = message["Attachments"]
    pdf = mailpit.get(f"/api/v1/message/{summary['ID']}/part/{attachment['PartID']}")
    assert pdf.startswith(b"%PDF-") and hashlib.sha256(pdf).hexdigest() == draft["attachments"][0]["sha256"]  # the very bytes the owner previewed


def test_concurrent_workers_deliver_a_message_exactly_once(mailpit):
    async def go():
        store, emails = await sender_store(mailpit), InMemoryEmailStore()
        saved = await emails.create_package(package(), [])
        await emails.approve_reviewed(saved.id, package_hash=saved.package_hash, message_id="<once@example.test>")
        await emails.queue_draft(saved.id, dispatch_at=datetime.now(UTC) - timedelta(seconds=1))
        sender = MailSender(store, tls_context=mailpit.tls)
        return await asyncio.gather(*(dispatch_due_drafts(emails, send_fn=sender) for _ in range(4)))

    assert sum(asyncio.run(go())) == 1
    assert len(mailpit.messages()) == 1


def test_a_bcc_recipient_is_an_envelope_recipient_only_and_is_in_no_transmitted_header():
    async def go():
        fake = await FakeSmtp("accept").start()
        try:
            store = await plain_store(fake.port)
            draft = package(recipients=Recipients(to=["a@example.org"], cc=["b@example.org"], bcc=["hidden.person@example.org"]))
            await MailSender(store, timeout=2)(draft)
            return fake.rcpts, fake.received[0]
        finally:
            await fake.stop()

    rcpts, data = asyncio.run(go())
    assert sorted(rcpts) == ["a@example.org", "b@example.org", "hidden.person@example.org"]  # the hidden address is delivered to...
    assert "hidden.person@example.org" not in data and "Bcc" not in data  # ...but appears nowhere in what is transmitted


def test_the_sender_test_reaches_the_typed_inbox_through_real_smtp_with_fixed_text_and_no_attachment(mailpit):
    async def go():
        store, emails, meetings = await sender_store(mailpit), InMemoryEmailStore(), InMemoryMeetingStore()
        service = MeetingEmailService(emails=emails, meetings=meetings, senders=store, groups=InMemoryGroupStore(), send_fn=MailSender(store, tls_context=mailpit.tls))
        return await service.send_test("Owner.Test.Inbox@Example.org")

    result = asyncio.run(go())
    assert result["status"] == "sent" and result["to"] == INBOX and result["provider_response"]
    [summary] = mailpit.messages()
    message = mailpit.message(summary["ID"])
    assert message["Subject"] == "Reachy test email" and message["From"]["Address"] == USER and [a["Address"] for a in message["To"]] == [INBOX]
    assert message["Attachments"] == [] and "test message from Reachy" in message["Text"] and "no meeting content" in message["Text"]


def test_a_test_email_with_a_wrong_password_fails_without_leaking_it_and_nothing_arrives(mailpit):
    async def go():
        store, emails, meetings = await sender_store(mailpit, password="wrong-password"), InMemoryEmailStore(), InMemoryMeetingStore()
        service = MeetingEmailService(emails=emails, meetings=meetings, senders=store, groups=InMemoryGroupStore(), send_fn=MailSender(store, tls_context=mailpit.tls))
        return await service.send_test(INBOX)

    result = asyncio.run(go())
    assert result["status"] == "failed" and "authentication failed" in result["error"] and "wrong-password" not in str(result)
    assert mailpit.messages() == []


# ---- failures ------------------------------------------------------------------------------------------------------------------------------------

def test_authentication_failure_at_dispatch_fails_the_message_once_without_retrying_or_leaking_the_credential(mailpit):
    async def go():
        store, emails = await sender_store(mailpit, password="wrong-password"), InMemoryEmailStore()
        saved = await emails.create_package(package(), [])
        await emails.approve_reviewed(saved.id, package_hash=saved.package_hash, message_id="<x@example.test>")
        await emails.queue_draft(saved.id, dispatch_at=datetime.now(UTC) - timedelta(seconds=1))
        sender = MailSender(store, tls_context=mailpit.tls)
        await dispatch_due_drafts(emails, send_fn=sender)
        await dispatch_due_drafts(emails, send_fn=sender, now=datetime.now(UTC) + timedelta(hours=1))
        return await emails.get_draft(saved.id), await emails.list_events(saved.id)

    final, events = asyncio.run(go())
    assert final.status == DraftStatus.FAILED and final.attempts == 1 and "authentication failed" in final.last_error
    assert "wrong-password" not in str(final.model_dump()) and "wrong-password" not in str(events)
    assert mailpit.messages() == []


def test_missing_or_deleted_credentials_fail_safely_and_nothing_is_sent(mailpit):
    async def go():
        store = await sender_store(mailpit)
        store._password = None  # the stored credential is gone (disconnected or lost)
        with pytest.raises(SendRefused, match="credential is missing"):
            await MailSender(store, tls_context=mailpit.tls)(package())
        disabled = await sender_store(mailpit, enabled=False)
        with pytest.raises(SendRefused, match="turned off"):
            await MailSender(disabled, tls_context=mailpit.tls)(package())

    asyncio.run(go())
    assert mailpit.messages() == []


def test_an_unreachable_server_is_transient_and_is_retried_with_backoff_then_fails(mailpit):
    async def go():
        store = await sender_store(mailpit, port=free_port())  # nothing listens here
        emails = InMemoryEmailStore()
        saved = await emails.create_package(package(), [])
        await emails.approve_reviewed(saved.id, package_hash=saved.package_hash, message_id="<x@example.test>")
        await emails.queue_draft(saved.id, dispatch_at=datetime.now(UTC) - timedelta(seconds=1))
        sender = MailSender(store, tls_context=mailpit.tls, timeout=2)
        first = datetime.now(UTC)
        await dispatch_due_drafts(emails, send_fn=sender, now=first)
        one = await emails.get_draft(saved.id)
        after_one = (one.status, one.attempts, one.dispatch_at)  # a snapshot: the in-memory store hands out live objects
        for step in (1, 2, 3):
            await dispatch_due_drafts(emails, send_fn=sender, now=first + timedelta(hours=step))
        return after_one, await emails.get_draft(saved.id)

    after_one, final = asyncio.run(go())
    assert after_one[0] == DraftStatus.QUEUED and after_one[1] == 1 and after_one[2] > datetime.now(UTC) - timedelta(seconds=5)
    assert final.status == DraftStatus.FAILED and final.attempts == 3 and "gave up" in final.last_error


def test_a_message_the_server_accepted_but_never_acknowledged_is_unknown_and_never_resent():
    async def go():
        fake = await FakeSmtp("hang").start()
        try:
            store, emails = await plain_store(fake.port), InMemoryEmailStore()
            saved = await emails.create_package(package(sender=USER), [])
            await emails.approve_reviewed(saved.id, package_hash=saved.package_hash, message_id="<x@example.test>")
            await emails.queue_draft(saved.id, dispatch_at=datetime.now(UTC) - timedelta(seconds=1))
            sender = MailSender(store, timeout=1)
            await dispatch_due_drafts(emails, send_fn=sender)
            await dispatch_due_drafts(emails, send_fn=sender, now=datetime.now(UTC) + timedelta(hours=2))
            return fake.received, await emails.get_draft(saved.id)
        finally:
            await fake.stop()

    received, final = asyncio.run(go())
    assert len(received) == 1 and "Meeting minutes: Weekly sync" in received[0]  # the server really did receive it: the ambiguity is genuine
    assert final.status == DraftStatus.UNKNOWN_DELIVERY and final.attempts == 1 and "no final answer" in final.last_error


@pytest.mark.parametrize("mode, error, status", [("rcpt_refused", SendRefused, DraftStatus.FAILED), ("defer", SendTransient, DraftStatus.QUEUED)])
def test_a_refused_recipient_is_final_and_a_deferral_is_retried(mode, error, status):
    async def go():
        fake = await FakeSmtp(mode).start()
        try:
            store, emails = await plain_store(fake.port), InMemoryEmailStore()
            with pytest.raises(error):
                await MailSender(store, timeout=2)(package())
            saved = await emails.create_package(package(sender=USER), [])
            await emails.approve_reviewed(saved.id, package_hash=saved.package_hash, message_id="<x@example.test>")
            await emails.queue_draft(saved.id, dispatch_at=datetime.now(UTC) - timedelta(seconds=1))
            await dispatch_due_drafts(emails, send_fn=MailSender(store, timeout=2))
            return await emails.get_draft(saved.id)
        finally:
            await fake.stop()

    final = asyncio.run(go())
    assert final.status == status and final.attempts == 1


def test_a_worker_that_died_mid_send_leaves_the_message_unknown_and_the_next_loop_does_not_resend_it(mailpit):
    async def go():
        store, emails = await sender_store(mailpit), InMemoryEmailStore()
        saved = await emails.create_package(package(), [])
        await emails.approve_reviewed(saved.id, package_hash=saved.package_hash, message_id="<x@example.test>")
        await emails.queue_draft(saved.id, dispatch_at=datetime.now(UTC) - timedelta(seconds=1))
        assert (await emails.claim_due(datetime.now(UTC))).status == DraftStatus.SENDING  # the previous process claimed it and died
        task = asyncio.create_task(run_dispatch_loop(emails, send_fn=MailSender(store, tls_context=mailpit.tls), interval_seconds=0.1))
        await asyncio.sleep(0.6)
        task.cancel()
        return await emails.get_draft(saved.id)

    final = asyncio.run(go())
    assert final.status == DraftStatus.UNKNOWN_DELIVERY and "interrupted" in final.last_error or "stopped" in final.last_error
    assert mailpit.messages() == []


def test_an_attachment_that_cannot_be_read_back_fails_the_message_before_anything_is_sent(mailpit):
    async def go():
        store, emails = await sender_store(mailpit), InMemoryEmailStore()
        saved = await emails.create_package(package(), [("m.pdf", "application/pdf", b"%PDF-1.4 original")])
        await emails.approve_reviewed(saved.id, package_hash=saved.package_hash, message_id="<x@example.test>")
        await emails.queue_draft(saved.id, dispatch_at=datetime.now(UTC) - timedelta(seconds=1))
        emails._blobs[saved.id] = []  # the stored bytes are missing at dispatch time
        await dispatch_due_drafts(emails, send_fn=MailSender(store, tls_context=mailpit.tls))
        return await emails.get_draft(saved.id)

    final = asyncio.run(go())
    assert final.status == DraftStatus.FAILED and "attachment" in final.last_error
    assert mailpit.messages() == []
