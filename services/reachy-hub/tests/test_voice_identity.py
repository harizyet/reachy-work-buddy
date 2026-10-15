"""Shared voice identity (Phase 32A.V, ADR 0041): enrollment, verification states, evidence lifetime, encryption at rest,
and the route/authority boundaries. The embedding service is replaced by a deterministic fake whose vectors are unit vectors
at an angle taken from the clip's tag, so cosine similarity between two clips is cos(angle difference) and every threshold
case is exact. A real-model run is in docs/verification/phase-32a-voice-identity-*.md, not here."""

import asyncio
import json
import math

import httpx
import pytest
from fastapi.testclient import TestClient
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.enrollment_store import InMemoryEnrollmentStore
from reachy_hub.keyring import Keyring, KeyringUnavailable
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.user_store import InMemoryUserStore
from reachy_hub.voice_identity import (
    Embedding,
    EmbeddingRejected,
    EmbeddingUnavailable,
    EvidenceLedger,
    VoiceIdentityConfig,
    VoiceIdentityService,
    assess,
    centroid,
    cosine,
)
from reachy_hub.voice_profiles import InMemoryVoiceProfileStore, load_template, seal

from shared.models.trust import SpeakerEvidence
from shared.models.voice_identity import ClientKind, ClientProvenance, VoiceState

CSRF = {"X-Reachy-CSRF": "1"}
ANDROID = {"X-Reachy-Client-Kind": "android", "X-Reachy-Client-Id": "install-1", "X-Reachy-Device-Id": "phone"}
PHONE = ClientProvenance(client_kind=ClientKind.ANDROID, client_id="install-1", device_id="phone")
KEYRING = Keyring("k1", {"k1": bytes(range(32))})
CALIBRATED = VoiceIdentityConfig(enabled=True, accept_threshold=0.8, uncertain_threshold=0.5, calibration_version="test-cal")
UNCALIBRATED = VoiceIdentityConfig(enabled=True)


def wav(tag: str) -> bytes:
    return b"RIFF" + bytes(4) + b"WAVE" + bytes(32) + tag.encode()


class FakeEmbedder:
    """Tag `a<degrees>` with optional `!short`, `!quiet`, `!clipped`; `!down` and `!bad` simulate the service."""

    model_version = "fake@1"

    def __init__(self):
        self.calls = 0

    async def embed(self, data: bytes) -> Embedding:
        self.calls += 1
        tag = data[44:].decode()
        if "!down" in tag:
            raise EmbeddingUnavailable()
        if "!bad" in tag:
            raise EmbeddingRejected()
        angle = math.radians(float(tag.split("!")[0].removeprefix("a")))
        return Embedding(
            [math.cos(angle), math.sin(angle), 0.0, 0.0], self.model_version, 3.0, 0.3 if "!short" in tag else 3.0,
            -60.0 if "!quiet" in tag else -20.0, 0.1 if "!clipped" in tag else 0.0,
        )

    async def healthy(self) -> bool:
        return True


OWNER_SAMPLES = ["a-3", "a0", "a3", "a-2", "a2"]


def make_service(config=CALIBRATED, *, clock=None):
    kwargs = {"clock": clock} if clock else {}
    return VoiceIdentityService(config, FakeEmbedder(), store=InMemoryVoiceProfileStore(), keyring=KEYRING, **kwargs)


async def enroll(service, tags=OWNER_SAMPLES):
    for tag in tags:
        await service.add_sample("owner", wav(tag))
    return await service.commit("owner", PHONE, consent=True)


def run(coro):
    return asyncio.run(coro)


# --- math and quality -----------------------------------------------------------------------------------

def test_cosine_and_centroid_are_scale_free():
    assert cosine([1, 0], [5, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 2]) == pytest.approx(0.0)
    assert centroid([[1, 0], [0, 1]]) == pytest.approx([math.sqrt(0.5)] * 2)


def test_assess_names_every_quality_failure():
    assert assess(Embedding([1.0], "m", 3, 3, -20, 0), 1.0) == []
    assert assess(Embedding([1.0], "m", 3, 0.2, -60, 0.5), 1.0) == ["too_little_speech", "too_quiet", "clipped"]


# --- enrollment and encryption at rest ----------------------------------------------------------------

def test_enrollment_requires_consent_enough_good_samples_and_one_voice():
    async def scenario():
        service = make_service()
        for tag in ["a0", "a2", "a-2", "a1!quiet", "a1!short"]:  # three usable, two not
            await service.add_sample("owner", wav(tag))
        with pytest.raises(Exception, match="consent_required"):
            await service.commit("owner", PHONE, consent=False)
        with pytest.raises(Exception, match="not_enough_samples"):
            await service.commit("owner", PHONE, consent=True)
        view = service.draft_view("owner")
        assert view.usable_samples == 3 and [s.reasons for s in view.samples][3:] == [["too_quiet"], ["too_little_speech"]]
        service.discard_draft("owner")
        for tag in ["a0", "a2", "a90", "a92", "a-90"]:  # two people in one session
            await service.add_sample("owner", wav(tag))
        with pytest.raises(Exception, match="inconsistent_samples"):
            await service.commit("owner", PHONE, consent=True)
        assert await service.store.get("owner") is None  # nothing was stored by any failed commit
    run(scenario())


def test_stored_profile_is_ciphertext_bound_to_owner_and_model():
    async def scenario():
        service = make_service()
        info = await enroll(service)
        row = await service.store.get("owner")
        assert info.version == 1 and info.sample_count == 5 and row.key_id == "k1"
        template = load_template(KEYRING, row)
        assert template == pytest.approx(centroid([[math.cos(math.radians(a)), math.sin(math.radians(a)), 0, 0] for a in (-3, 0, 3, -2, 2)]))
        digits = json.dumps(template[0])[:8].encode()
        assert digits not in row.ciphertext and b"template" not in row.ciphertext
        for tampered in ({"owner_id": "someone-else"}, {"model_version": "fake@2"}, {"profile_id": "other"}):
            with pytest.raises(KeyringUnavailable):
                load_template(KEYRING, type(row)(**{**row.__dict__, **tampered}))
        with pytest.raises(KeyringUnavailable):
            load_template(Keyring("k1", {"k1": bytes(32)}), row)
    run(scenario())


def test_reenrol_replaces_in_place_and_invalidates_evidence_delete_removes_it():
    async def scenario():
        service = make_service()
        await enroll(service)
        first = await service.verify("owner", wav("a0"), PHONE, utterance_id="u1")
        assert service.ledger.current("owner", "install-1", "u1") is first
        assert (await enroll(service, ["a80", "a82", "a78", "a81", "a79"])).version == 2
        assert service.ledger.current("owner", "install-1", "u1") is None  # A13: old evidence gone with the old template
        assert (await service.verify("owner", wav("a0"), PHONE, utterance_id="u2")).state == VoiceState.NOT_VERIFIED  # the new template is the only one
        assert await service.delete_profile("owner") and await service.store.get("owner") is None
        assert (await service.verify("owner", wav("a80"), PHONE, utterance_id="u3")).state == VoiceState.UNAVAILABLE
        assert not await service.delete_profile("owner")
    run(scenario())


# --- verification states ----------------------------------------------------------------------------------

def test_verification_states_follow_calibrated_thresholds():
    async def scenario():
        service = make_service()
        await enroll(service)
        states = {tag: (await service.verify("owner", wav(tag), PHONE, utterance_id=tag)).state
                  for tag in ["a5", "a-10", "a55", "a90", "a180"]}
        assert states == {"a5": VoiceState.VERIFIED, "a-10": VoiceState.VERIFIED, "a55": VoiceState.UNCERTAIN,
                          "a90": VoiceState.NOT_VERIFIED, "a180": VoiceState.NOT_VERIFIED}
    run(scenario())


def test_poor_audio_and_failures_never_become_verified_or_raise():
    async def scenario():
        service = make_service()
        await enroll(service)
        for tag, state, reason in [("a0!short", VoiceState.UNCERTAIN, "too_little_speech"), ("a0!quiet", VoiceState.UNCERTAIN, "too_quiet"),
                                   ("a0!clipped", VoiceState.UNCERTAIN, "clipped"), ("a0!down", VoiceState.UNAVAILABLE, "service_unavailable"),
                                   ("a0!bad", VoiceState.UNAVAILABLE, "audio_rejected")]:
            evidence = await service.verify("owner", wav(tag), PHONE, utterance_id="u")
            assert (evidence.state, reason in evidence.quality_reasons) == (state, True), tag
            assert not evidence.qualifies(service._clock())
        service.embedder.model_version = "fake@2"
        assert (await service.verify("owner", wav("a0"), PHONE, utterance_id="u")).quality_reasons == ["model_changed_reenroll"]
    run(scenario())


def test_without_an_approved_calibration_nothing_is_verified():
    async def scenario():
        service = make_service(UNCALIBRATED)
        await enroll(service)
        evidence = await service.verify("owner", wav("a0"), PHONE, utterance_id="u")
        assert evidence.state == VoiceState.UNAVAILABLE and evidence.quality_reasons == ["not_calibrated"] and not evidence.qualifies(0)
        assert not VoiceIdentityConfig(enabled=True, accept_threshold=0.5, uncertain_threshold=0.8).calibrated  # inverted thresholds are not a calibration
    run(scenario())


def test_unreadable_profile_and_missing_storage_are_unavailable_not_errors():
    async def scenario():
        service = make_service()
        await enroll(service)
        service.keyring = Keyring("k1", {"k1": bytes(32)})
        assert (await service.verify("owner", wav("a0"), PHONE, utterance_id="u")).quality_reasons == ["profile_unreadable"]
        bare = VoiceIdentityService(CALIBRATED, FakeEmbedder())
        assert (await bare.verify("owner", wav("a0"), PHONE, utterance_id="u")).quality_reasons == ["storage_unavailable"]
    run(scenario())


# --- evidence lifetime and binding (A16) ------------------------------------------------------------------

def test_evidence_is_bound_to_utterance_session_and_expires():
    async def scenario():
        now = [100.0]
        service = make_service(clock=lambda: now[0])
        await enroll(service)
        evidence = await service.verify("owner", wav("a0"), PHONE, utterance_id="u1", session_id="s1")
        ledger = service.ledger
        assert ledger.current("owner", "install-1", "u1", "s1") is evidence and evidence.qualifies(now[0])
        assert ledger.current("owner", "install-1", "u2", "s1") is None  # another utterance
        assert ledger.current("owner", "install-1", "u1", "s2") is None  # another session
        assert ledger.current("owner", "other-install", "u1", "s1") is None  # another client
        await service.verify("owner", wav("a0"), PHONE, utterance_id="u2", session_id="s1")
        assert ledger.current("owner", "install-1", "u1", "s1") is None  # replaced by the later turn
        now[0] += CALIBRATED.ttl_seconds + 0.1
        assert ledger.current("owner", "install-1", "u2", "s1") is None  # expired
        assert not evidence.qualifies(now[0])
    run(scenario())


def test_ledger_invalidate_is_per_owner():
    async def scenario():
        ledger = EvidenceLedger()
        service = make_service()
        await enroll(service)
        mine = await service.verify("owner", wav("a0"), PHONE, utterance_id="u")
        ledger.put(mine)
        ledger.invalidate("someone-else")
        assert ledger.current("owner", "install-1", "u") is mine
        ledger.invalidate("owner")
        assert ledger.current("owner", "install-1", "u") is None
    run(scenario())


def test_robot_compatible_projection():
    async def scenario():
        service = make_service()
        await enroll(service)
        good = await service.verify("owner", wav("a0"), PHONE, utterance_id="u")
        robot = good.to_speaker_evidence(robot_id="r1", voice_session_id="vs", turn=3)
        assert isinstance(robot, SpeakerEvidence) and robot.accepted and robot.qualifies(good.issued_monotonic) and robot.turn == 3
        assert robot.spoof_check == "unavailable"
        none = await service.verify("owner", wav("a0!down"), PHONE, utterance_id="u2")
        assert none.to_speaker_evidence(robot_id="r1", voice_session_id="vs", turn=4) is None  # outage: the robot path caps at T0
    run(scenario())


# --- routes -------------------------------------------------------------------------------------------------

def make_client(config=CALIBRATED, **kwargs):
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    service_store = kwargs.pop("voice_profile_store", InMemoryVoiceProfileStore())
    embedder = kwargs.pop("voice_embedder", FakeEmbedder())
    return TestClient(create_app(
        user_store=users, registry=InMemoryRobotRegistry(), session_store=InMemorySessionStore(), audit_log=InMemoryAuditLog(),
        notification_queue=InMemoryNotificationQueue(), enrollment_store=InMemoryEnrollmentStore(), run_heartbeat_task=False,
        run_telegram_poll_task=False, session_secret_key="test-session-secret", remote_ui_token="test-token",
        voice_identity_config=config, voice_embedder=embedder, voice_profile_store=service_store, voice_keyring=KEYRING, **kwargs,
    ))


def login(client):
    assert client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF).status_code == 200


def reauth(client):
    assert client.post("/owner-recognition/reauth", json={"password": "correct-password"}, headers=CSRF).status_code == 200


def post_audio(client, path, tag, headers=None):
    return client.post(path, content=wav(tag), headers={**CSRF, **ANDROID, "content-type": "audio/wav", **(headers or {})})


def enrol_via_api(client):
    for tag in OWNER_SAMPLES:
        assert post_audio(client, "/voice-identity/enrollment/samples", tag).status_code == 200
    reauth(client)
    return client.post("/voice-identity/enrollment/commit", json={"consent": True}, headers={**CSRF, **ANDROID})


def test_routes_are_owner_cookie_only_with_csrf_and_fresh_reauth():
    client = make_client()
    bearer = {"Authorization": "Bearer test-token"}
    assert client.get("/voice-identity/status").status_code == 401
    assert client.get("/voice-identity/status", headers=bearer).status_code == 401  # no bearer path to biometrics
    assert client.post("/voice-identity/verify", content=wav("a0"), headers={**ANDROID, **bearer}).status_code in (401, 403)
    login(client)
    assert client.post("/voice-identity/verify", content=wav("a0"), headers=ANDROID).status_code == 403  # no CSRF header
    assert client.post("/voice-identity/enrollment/commit", json={"consent": True}, headers={**CSRF, **ANDROID}).status_code == 401  # no fresh reauth
    assert client.delete("/voice-identity/profile", headers=CSRF).status_code == 401


def test_disabled_by_default_hides_everything_but_the_status():
    client = make_client(VoiceIdentityConfig())
    login(client)
    assert client.get("/voice-identity/status").json()["enabled"] is False
    assert post_audio(client, "/voice-identity/verify", "a0").status_code == 404
    assert post_audio(client, "/voice-identity/enrollment/samples", "a0").status_code == 404
    assert post_audio(client, "/voice-identity/turn", "a0").status_code == 404


def test_audio_and_provenance_validation():
    client = make_client()
    login(client)
    path = "/voice-identity/verify"
    assert client.post(path, content=wav("a0"), headers=CSRF).status_code == 422  # no provenance
    assert client.post(path, content=wav("a0"), headers={**CSRF, **ANDROID, "X-Reachy-Client-Kind": "toaster"}).status_code == 422
    assert client.post(path, content=b"not a wav file at all" * 5, headers={**CSRF, **ANDROID}).status_code == 422
    assert client.post(path, content=b"RIFF" + bytes(4) + b"WAVE" + bytes(3 * 1024 * 1024), headers={**CSRF, **ANDROID}).status_code == 413


def test_enrol_verify_status_and_delete_over_http_never_expose_scores_or_templates():
    client = make_client()
    login(client)
    committed = enrol_via_api(client)
    assert committed.status_code == 200, committed.text
    status = client.get("/voice-identity/status").json()
    assert status["profile"]["sample_count"] == 5 and status["profile"]["enrolled_by"]["client_id"] == "install-1" and status["draft"] is None
    results = {}
    for tag in ["a4", "a55", "a90"]:
        response = post_audio(client, "/voice-identity/verify", tag, {"X-Reachy-Utterance-Id": f"utt-{tag}"})
        assert response.status_code == 200
        results[tag] = response.json()
    assert [r["state"] for r in results.values()] == ["verified", "uncertain", "not_verified"]
    assert results["a4"]["utterance_id"] == "utt-a4" and 0 < results["a4"]["expires_in_seconds"] <= 10 and results["a4"]["replay_protection"] == "none"
    blob = json.dumps([status, results, committed.json()])
    assert "similarity" not in blob and "score" not in blob and "template" not in blob and "embedding" not in blob
    assert client.get("/auth/me").status_code == 200  # a negative result never touches the login
    reauth(client)
    assert client.delete("/voice-identity/profile", headers=CSRF).json() == {"deleted": True}
    assert post_audio(client, "/voice-identity/verify", "a4").json()["state"] == "unavailable"


def test_draft_review_and_removal_over_http():
    client = make_client()
    login(client)
    first = post_audio(client, "/voice-identity/enrollment/samples", "a0!quiet").json()
    assert first["quality_ok"] is False and first["reasons"] == ["too_quiet"]
    assert client.delete(f"/voice-identity/enrollment/samples/{first['sample_id']}", headers=CSRF).status_code == 200
    assert client.delete(f"/voice-identity/enrollment/samples/{first['sample_id']}", headers=CSRF).status_code == 404
    post_audio(client, "/voice-identity/enrollment/samples", "a0")
    assert client.get("/voice-identity/status").json()["draft"]["usable_samples"] == 1
    assert client.delete("/voice-identity/enrollment", headers=CSRF).status_code == 200
    assert client.get("/voice-identity/status").json()["draft"] is None


def test_embedding_service_outage_is_503_for_enrolment_but_a_state_for_verification():
    class Down(FakeEmbedder):
        async def embed(self, data):
            raise EmbeddingUnavailable()
    client = make_client(voice_embedder=Down())
    login(client)
    assert post_audio(client, "/voice-identity/enrollment/samples", "a0").status_code == 503
    assert post_audio(client, "/voice-identity/verify", "a0").json()["state"] == "unavailable"


# --- the combined turn: one capture, STT and verification, conversation unchanged ------------------------

class FakeSTT:
    def __init__(self, text="hello there"):
        self.text, self.seen = text, []

    def transcribe(self, wav_bytes, vocabulary=()):
        self.seen.append(wav_bytes)
        return self.text


def core_client():
    """A hermetic in-memory Companion Core, built as the /voice/turn tests build theirs (tests cannot import each other under importlib mode)."""
    from companion_core.app import create_app as create_core
    from companion_core.calendar.store import InMemoryCalendarStore
    from companion_core.consent.store import InMemoryConfirmationStore
    from companion_core.email.store import InMemoryEmailStore
    from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
    from companion_core.meetings.store import InMemoryMeetingStore
    from companion_core.memory.store import InMemoryMemoryStore
    from companion_core.persona.store import InMemoryPersonaStore
    from companion_core.planner.store import InMemoryPlannerStore
    from companion_core.rag.store import InMemoryDocumentStore
    from companion_core.tasks.store import InMemoryTaskStore
    from companion_core.websearch.store import InMemorySearchSettingsStore

    core = create_core(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(),
        meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False,
    )
    return CompanionCoreClient("http://companion-core", transport=httpx.ASGITransport(app=core))


def test_turn_reads_one_capture_twice_and_returns_a_spoken_conversation_plus_state():
    stt = FakeSTT()
    client = make_client(stt=stt, companion_core_client=core_client())
    login(client)
    assert enrol_via_api(client).status_code == 200
    response = post_audio(client, "/voice-identity/turn", "a2", {"X-Reachy-Utterance-Id": "utt-1"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript"] == "hello there" and body["message"]["reply"] and body["voice"]["state"] == "verified"
    assert stt.seen == [wav("a2")]  # STT read the very bytes that were verified
    assert client.app.state.voice_identity.ledger.current("default-user", "install-1", "utt-1") is not None


def test_turn_without_conversation_returns_only_the_transcript_and_state():
    stt = FakeSTT("begin meeting recording")
    client = make_client(stt=stt, companion_core_client=core_client())
    login(client)
    assert enrol_via_api(client).status_code == 200
    body = post_audio(client, "/voice-identity/turn?converse=false", "a1").json()
    assert body["transcript"] == "begin meeting recording" and body["message"] is None and body["voice"]["state"] == "verified"


def test_turn_continues_when_verification_fails_or_there_is_no_profile():
    client = make_client(stt=FakeSTT(), companion_core_client=core_client())
    login(client)
    body = post_audio(client, "/voice-identity/turn", "a2").json()  # no profile enrolled
    assert body["message"]["reply"] and body["voice"]["state"] == "unavailable"
    assert client.get("/auth/me").status_code == 200  # a non-result never touches the login


def test_a_verified_voice_does_not_unlock_what_a_spoken_turn_cannot_do():
    """ADR 0011 / ADR 0024: the turn is a voice-modality message whatever the evidence says; core still refuses the text-only action."""
    client = make_client(stt=FakeSTT("send draft hello"), companion_core_client=core_client())
    login(client)
    assert enrol_via_api(client).status_code == 200
    body = post_audio(client, "/voice-identity/turn", "a1").json()
    assert body["voice"]["state"] == "verified"
    assert "can't accept that confirmation by voice" in body["message"]["reply"]  # core's own ADR 0011 refusal, reached despite a verified owner voice


def test_turn_without_speech_is_rejected():
    client = make_client(stt=FakeSTT("   "), companion_core_client=core_client())
    login(client)
    assert post_audio(client, "/voice-identity/turn", "a0").status_code == 422


def test_keyring_is_seal_roundtrip():
    sealed = seal(KEYRING, owner_id="o", model_version="m", template=[0.6, 0.8], sample_count=5, enrolled_by=PHONE, consented_at=__import__("datetime").datetime.now())
    assert load_template(KEYRING, sealed) == [0.6, 0.8]


# --- the GV benchmark tool's arithmetic -------------------------------------------------------------------

def load_tool():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("vib", Path(__file__).parents[3] / "tools/voice_identity_benchmark.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def test_benchmark_tool_statistics_and_candidates():
    tool = load_tool()
    trials = ([{"kind": "genuine", "score": s, "condition": "quiet"} for s in (0.9, 0.85, 0.6, 0.3)]
              + [{"kind": "impostor", "score": s, "condition": "other_person"} for s in (0.2, 0.1)]
              + [{"kind": "attack", "score": 0.82, "condition": "replay"}])
    report = tool.summarize(trials, accept=0.8, uncertain=0.5)
    assert report["overall"]["matrix"] == {"genuine": {"verified": 2, "uncertain": 1, "not_verified": 1},
                                           "impostor": {"verified": 0, "uncertain": 0, "not_verified": 2},
                                           "attack": {"verified": 1, "uncertain": 0, "not_verified": 0}}
    assert report["overall"]["attack_acceptance"]["count"] == 1 and report["overall"]["far"]["count"] == 0 and report["overall"]["frr"]["count"] == 2
    assert report["by_condition"]["replay"]["trials"]["attack"] == 1
    low, high = tool.wilson(1, 3)
    assert 0 < low < 1 / 3 < high < 1 and tool.wilson(0, 0) is None
    grid = tool.sweep(trials)
    assert grid[0]["far"] == 1.0 and grid[-1]["far"] == 0.0 and grid[-1]["attack_acceptance"] == 0.0 and grid[-1]["frr"] == 1.0
    named = {c["name"]: c for c in tool.candidates(trials)}
    assert named["no_observed_false_accept"]["threshold"] > 0.82  # above the replay clip
    assert named["no_observed_false_accept"]["attack_acceptance"]["count"] == 0 and named["no_observed_false_accept"]["frr"]["count"] == 2
    assert named["at_most_one_observed_false_accept"]["threshold"] < named["no_observed_false_accept"]["threshold"]
    assert "equal_error_point" in named and tool.candidates([]) == []
    assert tool.percentiles([1, 2, 3, 4])["p50"] == 2.5


def test_benchmark_tool_reads_the_apps_export_and_classifies_attacks_whoever_they_claim_to_be():
    import io
    import json
    import zipfile

    tool = load_tool()
    assert [tool.trial_kind("owner", "owner", c) for c in ("quiet", "replay", "synthetic")] == ["genuine", "attack", "attack"]
    assert tool.trial_kind("alex", "owner", "quiet") == "impostor"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps([
            {"sample_id": "a", "content_type": "audio/wav", "label": "role=enroll;speaker=owner;condition=enroll"},
            {"sample_id": "b", "content_type": "audio/wav", "label": None},
        ]))
        archive.writestr("a.wav", b"one")
        archive.writestr("b.wav", b"two")
    entries, skipped = tool.entries_from_export(buffer.getvalue())
    assert skipped == 1 and entries == [{"role": "enroll", "speaker": "owner", "condition": "enroll", "name": "a", "data": b"one"}]


def test_benchmark_tool_end_to_end_with_a_fake_embedder_reports_candidates_but_selects_nothing():
    tool = load_tool()
    entries = [{"name": f"e{i}", "data": f"a{i}".encode(), "speaker": "owner", "role": "enroll", "condition": "enroll"} for i in (-2, -1, 0, 1, 2)]
    entries += [{"name": "g", "data": b"a5", "speaker": "owner", "role": "trial", "condition": "held_out"},
                {"name": "i", "data": b"a80", "speaker": "alex", "role": "trial", "condition": "other_person"},
                {"name": "r", "data": b"a50", "speaker": "owner", "role": "trial", "condition": "replay"}]

    def embed(data: bytes):
        angle = math.radians(float(data.decode().removeprefix("a")))
        return {"embedding": [math.cos(angle), math.sin(angle), 0, 0], "model_version": "fake@1", "speech_s": 3.0, "process_s": 0.1}

    report, code = tool.evaluate(entries, "owner", embed, None, None)
    assert code == 0 and report["trials"] == {"genuine": 1, "impostor": 1, "attack": 1}
    assert "thresholds_applied" not in report and "overall" not in report  # nothing is tabulated at a threshold nobody chose
    assert {c["name"] for c in report["threshold_candidates"]} >= {"no_observed_false_accept", "equal_error_point"}
    assert "No threshold has been selected" in report["limits"]
    with_thresholds, _ = tool.evaluate(entries, "owner", embed, 0.8, 0.5)
    assert with_thresholds["overall"]["trials"] == {"genuine": 1, "impostor": 1, "attack": 1}
    few, code = tool.evaluate(entries[:3], "owner", embed, None, None)
    assert code == 2 and few == {}
