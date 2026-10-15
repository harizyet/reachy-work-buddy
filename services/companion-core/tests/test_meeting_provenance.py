"""ADR 0040: verified processing provenance and the fixed disclosure text of a meeting-minutes email.

The processing record is produced by the real code paths (the worker stages, the output and title generators, the analysis runner, the cloud question) against in-memory stores and a scripted
model endpoint, and the email text is read from the real service. Nothing here asks a model what to say: the disclosure follows the records."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email import frame, mime
from companion_core.email.models import (
    MEETING_MINUTES_KIND,
    DraftStatus,
    EmailDraft,
    Recipients,
)
from companion_core.email.sender_config import (
    InMemoryMailSenderStore,
    SenderConfigError,
    SenderSettings,
)
from companion_core.email.store import InMemoryEmailStore
from companion_core.email.workflow import dispatch_due_drafts
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meeting_distribution.groups import InMemoryGroupStore
from companion_core.meeting_distribution.service import CONFIRM_WORD
from companion_core.meetings import provenance, worker
from companion_core.meetings.models import MeetingJobStatus, MeetingOutput
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

TOKEN = "service-secret"
HEADERS = {"X-Reachy-Service-Token": TOKEN}
SENDER = "reachy.minutes@example.test"
SEGMENTS = [{"start": 0.0, "end": 5.0, "text": "We agree to ship on Friday."}]
DIARIZATION = [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"}]
LOCAL_URL = "http://ovms/v1"
CLOUD_URL = "http://cloud.example.com/v1"


class Speech:
    """A transcription or diarization client whose endpoint is chosen by the test."""

    def __init__(self, base_url, segments):
        self.base_url, self._segments = base_url, segments

    async def transcribe(self, audio, *, filename, content_type):
        return self._segments

    diarize = transcribe


def model(request: httpx.Request) -> httpx.Response:
    system = json.loads(request.content)["messages"][0]["content"]
    if "You summarise meetings" in system:
        text = "The team agreed to ship on Friday."
    elif "You write meeting minutes" in system:
        text = "Topics discussed\n- Release\nDecisions\n- Ship on Friday"
    elif "You name meetings" in system:
        text = "TITLE: Release planning\nDESCRIPTION: The team agreed a release date."
    else:
        text = "- answer"
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


class World:
    """A core app with the email flag on, a meeting that has gone through the real worker stages, and a model endpoint that is local (`ovms`) or cloud (`cloud.example.com`)."""

    def __init__(self, *, host="smtp.gmail.com", transcription_url="http://transcription:8011", diarization_url="http://diarization:8010", local_url=LOCAL_URL, owner="Hariz", process=True):
        self.sent: list[EmailDraft] = []
        self.meetings, self.emails, self.senders = InMemoryMeetingStore(), InMemoryEmailStore(), InMemoryMailSenderStore()
        self.host, self.owner = host, owner

        async def send(draft: EmailDraft) -> str:
            self.sent.append(draft)
            return "2.0.0 OK queued"

        self.send = send
        self.on_request = lambda request: None
        self.app = create_app(
            calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=self.meetings, run_meeting_worker_task=False,
            memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=self.emails, email_send_fn=send, confirmation_store=InMemoryConfirmationStore(),
            llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
            run_email_dispatch_task=False, accounts_service_token=TOKEN, meeting_email_enabled=True, mail_sender_store=self.senders, recipient_group_store=InMemoryGroupStore(),
            email_send_delay_seconds=600, llm_transport=httpx.MockTransport(self._model))
        self.client = TestClient(self.app, headers=HEADERS)
        body = {"local": {"base_url": local_url, "model": "reachy-local"}, "cloud": {"base_url": CLOUD_URL, "model": "big", "api_key": "k"}, "routing": {"mode": "local_only"}}
        assert self.client.put("/settings/llm", json=body).status_code == 200
        self.meeting_id = asyncio.run(self._pipeline(transcription_url, diarization_url, process))
        asyncio.run(self._sender())

    def _model(self, request: httpx.Request) -> httpx.Response:
        self.on_request(request)
        return model(request)

    async def _pipeline(self, transcription_url, diarization_url, process):
        meeting = await self.meetings.create_meeting(title="Weekly sync", audio=b"RIFF....", source_filename="a.wav", content_type="audio/wav", participants=["Hariz"],
                                                     started_at=datetime(2026, 10, 14, 6, 0, tzinfo=UTC))
        if process:
            self.meetings._touch(meeting, status=MeetingJobStatus.TRANSCRIBING)
            await worker.transcribe(self.meetings, await self.meetings.get_meeting(meeting.id), Speech(transcription_url, SEGMENTS))
            await worker.diarize(self.meetings, await self.meetings.get_meeting(meeting.id), Speech(diarization_url, DIARIZATION))
            await worker.align_stage(self.meetings, await self.meetings.get_meeting(meeting.id))
        else:
            self.meetings._touch(meeting, status=MeetingJobStatus.COMPLETE, transcript_segments=SEGMENTS)
        return meeting.id

    async def _sender(self):
        await self.senders.save(SenderSettings(host=self.host, from_address=SENDER, username=SENDER, owner_name=self.owner), password="abcdabcdabcdabcd")
        await self.senders.record_verification(True, "ok")
        await self.senders.set_enabled(True)

    def generate(self, kind, model_name="local"):
        r = self.client.post(f"/meetings/{self.meeting_id}/outputs/{kind}", json={"model": model_name})
        assert r.status_code == 200, r.text
        return r.json()

    def both_outputs(self, model_name="local"):
        self.generate("summary", model_name)
        self.generate("minutes", model_name)

    def meeting(self):
        return asyncio.run(self.meetings.get_meeting(self.meeting_id))

    def events(self):
        return [(e.step, e.location) for e in self.meeting().processing_events]

    def verdict(self):
        return provenance.assess(self.meeting())

    def prepare(self, **body):
        r = self.client.post(f"/meetings/{self.meeting_id}/email/prepare", json=body)
        assert r.status_code == 200, r.text
        return r.json()

    def approve_and_queue(self, draft):
        approved = self.client.post(f"/meeting-email/drafts/{draft['id']}/approve", json={"package_hash": draft["package_hash"], "confirmation": CONFIRM_WORD})
        assert approved.status_code == 200, approved.text
        return self.client.post(f"/meeting-email/drafts/{draft['id']}/queue")

    def dispatch(self, minutes=11):
        send = self.app.state.meeting_email.guard_send(self.send)
        return asyncio.run(dispatch_due_drafts(self.emails, send_fn=send, now=datetime.now(UTC) + timedelta(minutes=minutes)))

    def sent_text(self):
        draft = self.sent[-1]
        return mime.build_message(draft, sender=SENDER, attachments=list(draft.attachment_blobs)).get_body(("plain",)).get_content()


# ---- where an endpoint is ----------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("url", "where"), [
    ("http://transcription:8011", "local"), ("http://localhost:8000", "local"), ("http://127.0.0.1:8000/v1", "local"), ("http://192.168.1.20:8080", "local"),
    ("http://10.1.2.3", "local"), ("http://172.20.0.5", "local"), ("http://100.101.102.103:9", "local"), ("http://[::1]:8000", "local"), ("http://llm.internal", "local"),
    ("http://nas.lan:8080", "local"), ("http://host.docker.internal:8080", "local"),
    ("https://api.example.com/v1", "unverified"), ("http://8.8.8.8", "unverified"), ("http://100.128.0.1", "unverified"), ("", "unverified"), (None, "unverified"), ("not a url", "unverified"),
])
def test_an_endpoint_is_local_only_when_its_address_or_name_is_private_and_a_public_name_is_never_assumed_private(url, where):
    assert provenance.endpoint_location(url) == where


# ---- the pipeline records what actually ran ------------------------------------------------------------------------------------------------------

def test_the_worker_stages_record_where_transcription_speaker_detection_and_alignment_ran():
    w = World()
    assert w.events() == [("transcription", "local"), ("diarization", "local"), ("speaker_processing", "local")]


def test_a_speech_service_at_a_public_address_is_recorded_as_unverified_not_local():
    w = World(transcription_url="https://speech.example.com", diarization_url="http://diarization:8010")
    assert ("transcription", "unverified") in w.events() and w.verdict().status == "unverified"


def test_outputs_are_recorded_with_where_the_model_ran_and_which_output_they_produced():
    w = World()
    w.both_outputs()
    meeting = w.meeting()
    assert meeting.summary.location == "local" and meeting.minutes.location == "local"
    by_step = {e.step: e for e in meeting.processing_events}
    assert by_step["summary"].subject == meeting.summary.generated_at.isoformat() and by_step["minutes"].location == "local"


def test_a_cloud_summary_is_recorded_as_external_before_the_text_exists_and_a_local_model_at_a_public_name_is_unverified():
    w = World()
    w.generate("summary", "cloud")
    assert ("summary", "external") in w.events()
    far = World(local_url="https://llm.example.com/v1")
    far.generate("summary")
    assert far.meeting().summary.location == "unverified" and ("summary", "unverified") in far.events()


def test_a_cloud_attempt_is_recorded_before_the_model_is_called_so_a_failed_call_still_counts():
    w = World()
    at_request = []
    w.on_request = lambda request: at_request.append([(e.step, e.location) for e in w.meetings._meetings[w.meeting_id].processing_events])
    w.generate("summary", "cloud")
    assert at_request and all(("summary", "external") in seen for seen in at_request)


def test_a_generated_title_and_correction_suggestions_are_recorded():
    w = World()
    assert w.client.post(f"/meetings/{w.meeting_id}/describe", json={"model": "local"}).status_code == 200
    assert ("title", "local") in w.events() and w.meeting().title_source == "generated"
    w.client.post(f"/meetings/{w.meeting_id}/corrections/suggest", json={"model": "cloud"})
    assert ("corrections", "external") in w.events()


def test_the_owner_choosing_the_cloud_model_for_a_question_about_the_meeting_is_recorded():
    w = World()
    body = {"session_id": "s1", "conversation_id": "c1", "channel": "web", "text": "What was decided?", "context_meeting_id": w.meeting_id}
    assert w.client.post("/conversation", json=body).status_code == 200
    assert ("conversation", "external") not in w.events()  # the default answers locally and records nothing external
    assert w.client.post("/conversation", json={**body, "force_frontier": True}).status_code == 200
    assert ("conversation", "external") in w.events()


# ---- the verdict -------------------------------------------------------------------------------------------------------------------------------

def test_local_only_when_every_needed_step_is_recorded_as_local():
    w = World()
    w.both_outputs()
    verdict = w.verdict()
    assert verdict.status == "local" and verdict.external_steps == [] and verdict.reasons == []


def test_missing_provenance_is_never_read_as_local():
    w = World(process=False)
    w.both_outputs()
    verdict = w.verdict()
    assert verdict.status == "unverified" and any("transcription" in r for r in verdict.reasons)
    assert provenance.assess(type("M", (), {"processing_events": [], "summary": None, "minutes": None, "title_source": "default"})()).status == "unverified"


def test_a_summary_with_no_matching_record_makes_the_verdict_unverified():
    w = World()
    w.both_outputs()
    old = MeetingOutput(text="Written before provenance was recorded.", tier="local")  # no location: never recorded
    asyncio.run(w.meetings.set_output(w.meeting_id, "summary", old))
    verdict = w.verdict()
    assert verdict.status == "unverified" and any("summary" in r for r in verdict.reasons)


def test_cloud_escalation_gives_external_naming_only_the_step_and_every_other_step_local():
    w = World()
    w.generate("summary", "cloud")
    w.generate("minutes")
    verdict = w.verdict()
    assert verdict.status == "external" and verdict.external_steps == ["summary"] and verdict.rest_local is True


def test_mixed_processing_is_external_and_does_not_claim_the_rest_is_private_when_it_cannot_show_it():
    w = World(process=False)  # no pipeline records at all
    w.generate("minutes", "cloud")
    verdict = w.verdict()
    assert verdict.status == "external" and verdict.external_steps == ["minutes"] and verdict.rest_local is False


def test_a_regenerated_summary_keeps_the_record_of_an_earlier_external_one():
    w = World()
    w.generate("summary", "cloud")
    w.generate("summary")  # regenerated locally
    w.generate("minutes")
    assert w.meeting().summary.location == "local"
    verdict = w.verdict()
    assert verdict.status == "external" and verdict.external_steps == ["summary"]  # the content was sent once; regenerating cannot unsend it


def test_regenerating_locally_after_an_unverified_output_does_not_clear_an_external_step_either():
    w = World()
    w.both_outputs()
    asyncio.run(w.meetings.record_processing(w.meeting_id, provenance.event("analysis", "external", subject="run-1")))
    assert w.verdict().status == "external"
    w.both_outputs()
    assert w.verdict().status == "external"


def test_an_analysis_included_in_the_message_needs_a_local_record_for_that_run():
    w = World()
    w.both_outputs()
    assert provenance.assess(w.meeting(), analysis_run="run-1").status == "unverified"
    asyncio.run(w.meetings.record_processing(w.meeting_id, provenance.event("analysis", "local", subject="run-1")))
    assert provenance.assess(w.meeting(), analysis_run="run-1").status == "local"
    assert provenance.assess(w.meeting(), analysis_run="run-2").status == "unverified"


def test_a_generated_title_needs_a_local_record_but_an_owners_own_title_does_not():
    w = World()
    w.both_outputs()
    asyncio.run(w.meetings.set_title(w.meeting_id, title="Release planning", description=None, source="generated"))
    assert w.verdict().status == "unverified"
    asyncio.run(w.meetings.set_title(w.meeting_id, title="Release planning", description=None, source="owner"))
    assert w.verdict().status == "local"


def test_the_analysis_runner_records_the_run_after_a_local_model_and_before_a_non_local_one():
    from companion_core.meeting_analysis.service import MeetingAnalysisService
    from companion_core.meeting_analysis.store import InMemoryMeetingAnalysisStore

    async def run(w, where):
        store = InMemoryMeetingAnalysisStore()
        seen = []

        async def locate():
            return where

        async def provider():
            async def ask(messages, max_tokens):
                seen.append([(e.step, e.location) for e in w.meetings._meetings[w.meeting_id].processing_events])  # sync read: we are inside a running loop
                return "{\"items\": []}"

            return ask, "m"

        service = MeetingAnalysisService(store, w.meetings, InMemoryTaskStore(), InMemoryPlannerStore(), lambda: asyncio.sleep(0, "UTC"), provider=provider, location=locate)
        meeting = await w.meetings.get_meeting(w.meeting_id)
        await service.enqueue(meeting.id)
        await service.process_next()
        return seen

    w = World()
    w.both_outputs()
    seen = asyncio.run(run(w, "local"))
    assert ("analysis", "local") in w.events() and all(("analysis", "local") not in call for call in seen)
    w = World()
    w.both_outputs()
    seen = asyncio.run(run(w, "external"))
    assert ("analysis", "external") in w.events() and all(("analysis", "external") in call for call in seen)  # recorded before any text left


# ---- the fixed text of the email -----------------------------------------------------------------------------------------------------------------

def test_a_local_only_meeting_states_it_in_the_required_words_and_still_discloses_the_gmail_transfer():
    w = World()
    w.both_outputs()
    text = w.prepare(to=["a@example.org"])["rendered_body"]
    assert "This meeting was processed entirely on private infrastructure. No meeting content was sent to external AI services." in text
    assert "delivered through Gmail" in text and "the email and its attachment are transmitted through Google's email service" in text
    assert text.index("This meeting was processed entirely") > text.index("Best regards,")


def test_the_identity_accuracy_and_review_text_come_from_the_template():
    w = World()
    w.both_outputs()
    text = w.prepare()["rendered_body"]
    for expected in ("Hi everyone,", "I'm Reachy, Hariz's personal AI assistant.", "on Hariz's behalf", "self-hosted AI assistant created by Hariz", "Meeting: Weekly sync",
                     "A note about accuracy:", "attributing comments to the wrong speaker", "Please let Hariz know", "Hariz's Personal AI Assistant", "Reviewed and approved by Hariz before sending."):
        assert expected in text, expected


def test_cloud_escalation_never_makes_the_local_only_claim_and_names_only_what_was_external():
    w = World()
    w.generate("summary", "cloud")
    w.generate("minutes")
    text = w.prepare()["rendered_body"]
    assert "processed entirely on private infrastructure" not in text and "No meeting content was sent" not in text
    assert "Some meeting content was processed by an external AI service for the summary. All other processing took place on private infrastructure." in text
    assert "cloud.example.com" not in text and "reachy-local" not in text and "big" not in text.split("Best regards,")[1]  # no provider, host or model names


def test_mixed_processing_with_missing_records_states_the_external_step_but_not_that_the_rest_was_private():
    w = World(process=False)
    w.generate("minutes", "cloud")
    text = w.prepare()["rendered_body"]
    assert "Some meeting content was processed by an external AI service for the minutes." in text
    assert "All other processing took place on private infrastructure" not in text and "entirely on private infrastructure" not in text


def test_missing_provenance_gets_the_neutral_architecture_statement_and_no_claim():
    w = World(process=False)
    w.both_outputs()
    d = w.prepare()
    assert frame.NEUTRAL in d["rendered_body"] and "entirely on private infrastructure" not in d["rendered_body"]
    assert d["processing"]["status"] == "unverified"


def test_the_delivery_sentence_is_always_present_and_names_the_provider_that_will_carry_the_message():
    w = World(host="mail.example.org")
    w.both_outputs()
    text = w.prepare()["rendered_body"]
    assert "delivered through an external email provider" in text and "Gmail" not in text.split("Best regards,")[1]
    gm = World()
    gm.both_outputs()
    no_pdf = gm.prepare(include_pdf=False)["rendered_body"]
    assert "delivered through Gmail, so the email is transmitted through Google's email service." in no_pdf and "attachment" not in no_pdf.split("Best regards,")[1]


def test_editing_the_body_cannot_remove_or_change_the_disclosures():
    w = World()
    w.both_outputs()
    d = w.prepare(to=["a@example.org"])
    edited = w.client.put(f"/meeting-email/drafts/{d['id']}", json={"body": "Just this."}).json()
    assert edited["rendered_body"].count("Just this.") == 1
    for fixed in ("Hi everyone,", "A note about accuracy:", "This meeting was processed entirely on private infrastructure.", "delivered through Gmail"):
        assert fixed in edited["rendered_body"]
    assert edited["text_before"] in edited["rendered_body"] and edited["text_after"] in edited["rendered_body"]


def test_what_is_sent_is_exactly_the_text_that_was_previewed_and_approved():
    w = World()
    w.both_outputs()
    d = w.prepare(to=["a@example.org"])
    assert w.approve_and_queue(d).status_code == 200
    assert w.dispatch() == 1
    sent = w.sent_text().replace("\r\n", "\n")
    assert sent.strip() == d["rendered_body"].strip() and "Reviewed and approved by Hariz" in sent


def test_a_meeting_package_without_its_frame_is_refused_when_building_the_message():
    draft = EmailDraft(to="a@example.org", subject="s", body="b", kind=MEETING_MINUTES_KIND, recipients=Recipients(to=["a@example.org"]), source={"meeting_id": "m"})
    with pytest.raises(mime.AddressError):
        mime.build_message(draft, sender=SENDER)
    assert mime.build_message(EmailDraft(to="a@example.org", subject="s", body="plain text draft"), sender=SENDER).get_content().strip() == "plain text draft"


def test_the_owners_name_is_required_so_the_message_always_says_whom_reachy_writes_for():
    w = World(owner="")
    w.both_outputs()
    r = w.client.post(f"/meetings/{w.meeting_id}/email/prepare", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_owner_name"
    with pytest.raises(SenderConfigError):
        asyncio.run(InMemoryMailSenderStore().save(SenderSettings(host="h.example", from_address=SENDER, owner_name="x" * 81), password=None))


# ---- approval, hashing and the delayed send stay in force -----------------------------------------------------------------------------------------

def test_the_package_hash_covers_the_disclosure_text_so_a_different_verdict_is_a_different_package():
    local, cloud = World(), World()
    local.both_outputs()
    cloud.generate("summary", "cloud")
    cloud.generate("minutes")
    assert local.prepare()["package_hash"] != cloud.prepare()["package_hash"]
    d = local.prepare(to=["a@example.org"])
    stored = asyncio.run(local.emails.get_draft(d["id"]))
    stored.source["frame"]["provenance"] = {"status": "local", "external_steps": [], "rest_local": True, "digest": "forged"}
    assert stored.package_hash != __import__("companion_core.email.models", fromlist=["package_hash"]).package_hash(stored, stored.sender)


def test_the_owner_still_has_to_type_send_and_the_message_still_waits_out_the_delay():
    w = World()
    w.both_outputs()
    d = w.prepare(to=["a@example.org"])
    wrong = w.client.post(f"/meeting-email/drafts/{d['id']}/approve", json={"package_hash": d["package_hash"], "confirmation": "yes"})
    assert wrong.status_code == 422
    assert w.approve_and_queue(d).status_code == 200
    assert w.dispatch(minutes=1) == 0 and w.sent == []
    assert w.dispatch(minutes=11) == 1


def test_a_cloud_regeneration_after_preparing_blocks_queueing_until_the_message_is_prepared_again():
    w = World()
    w.both_outputs()
    d = w.prepare(to=["a@example.org"])
    w.generate("summary", "cloud")
    assert w.client.get(f"/meeting-email/drafts/{d['id']}").json()["meeting_changed"] is True
    r = w.approve_and_queue(d)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "meeting_changed"


def test_a_cloud_question_after_preparing_changes_the_verdict_and_blocks_queueing_even_though_the_summary_is_unchanged():
    w = World()
    w.both_outputs()
    d = w.prepare(to=["a@example.org"])
    asyncio.run(w.meetings.record_processing(w.meeting_id, provenance.event("conversation", "external")))
    r = w.approve_and_queue(d)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "meeting_changed"
    fresh = w.prepare(to=["a@example.org"])
    assert "Some meeting content was processed by an external AI service for a question about the meeting." in fresh["rendered_body"]


def test_external_processing_in_the_undo_window_stops_the_send_and_nothing_goes_out():
    w = World()
    w.both_outputs()
    d = w.prepare(to=["a@example.org"])
    assert w.approve_and_queue(d).status_code == 200
    asyncio.run(w.meetings.record_processing(w.meeting_id, provenance.event("conversation", "external")))
    w.dispatch()
    assert w.sent == []
    final = asyncio.run(w.emails.get_draft(d["id"]))
    assert final.status is DraftStatus.FAILED and "approved" in (final.last_error or "")


def test_changing_the_mail_service_after_approval_blocks_queueing():
    w = World()
    w.both_outputs()
    d = w.prepare(to=["a@example.org"])
    approved = w.client.post(f"/meeting-email/drafts/{d['id']}/approve", json={"package_hash": d["package_hash"], "confirmation": CONFIRM_WORD})
    assert approved.status_code == 200
    asyncio.run(w.senders.save(SenderSettings(host="mail.example.org", from_address=SENDER, username=SENDER, owner_name="Hariz"), password="other-password"))
    asyncio.run(w.senders.record_verification(True, "ok"))
    asyncio.run(w.senders.set_enabled(True))
    r = w.client.post(f"/meeting-email/drafts/{d['id']}/queue")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sender_changed"


def test_the_sender_test_email_and_other_drafts_are_unaffected_by_the_guard():
    w = World()
    r = w.client.post("/meeting-email/sender/test", json={"to": "me@example.org"})
    assert r.status_code == 200
    assert w.sent and w.sent[-1].kind == "sender_test"


def test_the_sender_view_carries_the_owner_name_and_changing_it_does_not_switch_sending_off():
    w = World()
    view = w.client.get("/meeting-email/sender").json()
    assert view["owner_name"] == "Hariz" and view["enabled"] is True
    saved = w.client.put("/meeting-email/sender", json={"host": w.host, "port": 587, "security": "starttls", "from_address": SENDER, "username": SENDER, "owner_name": "  Hariz   Yet "}).json()
    assert saved["owner_name"] == "Hariz Yet" and saved["enabled"] is True
