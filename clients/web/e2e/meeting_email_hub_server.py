"""Real in-process hub in front of a REAL companion-core for the Phase 55 browser test: the meeting-minutes email flow with the real dispatch loop and the real sender. The only stand-in is
the mail server: a tiny SMTP server in this process that records what is transmitted, shown at GET /__mail (fixture only, never a deployment). The delay is short (5 s) so the browser test can
watch a message go out and also cancel one in time. The sender is pre-configured and enabled; verification and the credential flow are covered in the unit tests and against Mailpit.

    python e2e/meeting_email_hub_server.py PORT
"""

import asyncio
import hashlib
import importlib.util
import os
import sys
from datetime import UTC, datetime
from email import message_from_bytes
from email import policy as email_policy
from pathlib import Path

import httpx
import uvicorn

os.environ["EMAIL_SEND_DELAY_SECONDS"] = "5"
os.environ["EMAIL_DISPATCH_INTERVAL_SECONDS"] = "0.5"
tests = Path(__file__).resolve().parents[3] / "services" / "reachy-hub" / "tests" / "test_web_client.py"
spec = importlib.util.spec_from_file_location("test_web_client", tests)
module = importlib.util.module_from_spec(spec)
sys.modules["test_web_client"] = module
spec.loader.exec_module(module)

from companion_core.email.sender_config import InMemoryMailSenderStore, SenderSettings  # noqa: E402
from companion_core.meeting_distribution.groups import InMemoryGroupStore  # noqa: E402
from companion_core.meetings.models import MeetingJobStatus, MeetingOutput, speaker_basis  # noqa: E402
from reachy_hub.companion_core_client import CompanionCoreClient  # noqa: E402
from reachy_hub.enrollment_store import InMemoryEnrollmentStore  # noqa: E402

SENDER = "reachy.minutes@example.test"
RECEIVED: list[dict] = []


class Smtp:
    async def start(self):
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def _client(self, reader, writer):
        rcpts: list[str] = []

        async def say(line):
            writer.write(line.encode() + b"\r\n")
            await writer.drain()

        await say("220 fixture ESMTP")
        try:
            while line := await reader.readline():
                cmd = line.decode().strip().upper()
                if cmd.startswith(("EHLO", "HELO")):
                    await say("250-fixture")
                    await say("250 8BITMIME")
                elif cmd.startswith("RCPT"):
                    rcpts.append(line.decode().split("<", 1)[-1].split(">", 1)[0].lower())
                    await say("250 ok")
                elif cmd == "DATA":
                    await say("354 go ahead")
                    data = b""
                    while not data.endswith(b"\r\n.\r\n"):
                        data += await reader.readline()
                    message = message_from_bytes(data[:-5], policy=email_policy.default)
                    RECEIVED.append({
                        "subject": message["Subject"], "from": message["From"], "to": message["To"], "cc": message["Cc"], "headers": "\n".join(f"{k}: {v}" for k, v in message.items()), "rcpts": rcpts,
                        "body": message.get_body(preferencelist=("plain",)).get_content(),
                        "attachments": [{"filename": p.get_filename(), "type": p.get_content_type(), "sha256": hashlib.sha256(p.get_content()).hexdigest(), "size": len(p.get_content())} for p in message.iter_attachments()],
                    })
                    await say("250 2.0.0 OK queued as FIXTURE1")
                elif cmd == "QUIT":
                    await say("221 bye")
                    break
                else:
                    await say("250 ok")
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()


def build():
    core = module.create_core_app(
        calendar_store=module.InMemoryCalendarStore(), task_store=module.InMemoryTaskStore(), planner_store=module.InMemoryPlannerStore(), meeting_store=module.InMemoryMeetingStore(),
        run_meeting_worker_task=False, memory_store=module.InMemoryMemoryStore(), rag_store=module.InMemoryDocumentStore(), email_store=module.InMemoryEmailStore(),
        confirmation_store=module.InMemoryConfirmationStore(), llm_settings_store=module.InMemoryLLMSettingsStore(), llm_usage_store=module.InMemoryLLMUsageStore(),
        persona_store=module.InMemoryPersonaStore(), search_settings_store=module.InMemorySearchSettingsStore(), run_email_dispatch_task=False,
        meeting_email_enabled=True, mail_sender_store=InMemoryMailSenderStore(), recipient_group_store=InMemoryGroupStore(), email_send_delay_seconds=5)
    store = core.state.meeting_store

    async def seed():
        meeting = await store.create_meeting(title="Weekly sync", audio=b"x", source_filename="a.wav", content_type="audio/wav", participants=["Hariz"],
                                             started_at=datetime(2026, 10, 14, 6, 0, tzinfo=UTC))
        names = {"SPEAKER_00": "Priya Shah"}
        store._touch(meeting, status=MeetingJobStatus.COMPLETE, transcript_segments=[{"start": 0, "end": 3, "text": "SECRET-TRANSCRIPT-LINE hello"}], diarization_segments=[{"start": 0, "end": 3, "speaker": "SPEAKER_00"}],
                     aligned_segments=[{"start": 0, "end": 3, "text": "hello", "speaker": "SPEAKER_00"}], speaker_names=names,
                     summary=MeetingOutput(text="Priya Shah proposed shipping on Friday and the team agreed.", tier="local", speaker_basis=speaker_basis(names)),
                     minutes=MeetingOutput(text="Topics discussed\n- Release date\nDecisions\n- Ship on Friday", tier="local", speaker_basis=speaker_basis(names)))

    asyncio.run(seed())  # before the server's event loop exists (make_client below also runs its own)
    client = module.make_client(companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core)), accounts_service_token="e2e-service",
                                enrollment_store=InMemoryEnrollmentStore())
    client.cookies.clear()

    @client.app.get("/__mail")
    async def mail() -> list[dict]:
        return RECEIVED

    return client, core


async def serve(client, core, port: int):
    smtp = await Smtp().start()
    senders = core.state.mail_sender_store
    await senders.save(SenderSettings(host="127.0.0.1", port=smtp.port, security="none", from_address=SENDER, owner_name="Hariz"), password=None)
    await senders.record_verification(True, "fixture")
    await senders.set_enabled(True)
    from companion_core.email.sender import MailSender
    from companion_core.email.workflow import run_dispatch_loop

    loop_task = asyncio.create_task(run_dispatch_loop(core.state.email_store, send_fn=MailSender(core.state.mail_sender_store), interval_seconds=0.5))
    try:
        await uvicorn.Server(uvicorn.Config(client.app, host="127.0.0.1", port=port, log_level="warning")).serve()
    finally:
        loop_task.cancel()


if __name__ == "__main__":
    hub, core_app = build()  # synchronous: it seeds and builds the hub before the server's event loop exists
    asyncio.run(serve(hub, core_app, int(sys.argv[1])))
