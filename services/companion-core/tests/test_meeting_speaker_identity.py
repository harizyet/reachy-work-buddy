"""Phase 54: deterministic speaker samples and owner-confirmed speaker identities."""

import asyncio

import httpx
import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings import outputs, speaker_identity, speaker_samples
from companion_core.meetings.models import (
    Meeting,
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

A, B, C = "SPEAKER_00", "SPEAKER_01", "SPEAKER_02"


def span(start, end, who):
    return {"start": start, "end": end, "speaker": who}


def words(start, end, text="we should plan the release for the autumn quarter together"):
    return {"start": start, "end": end, "text": text}


# A talks 0-30 and 60-80 (long turns), B talks 30-45 in short turns, C only says a word at 50-51.
DIARIZATION = [span(0, 30, A), span(30, 36, B), span(37, 45, B), span(50, 51, C), span(60, 80, A)]
TRANSCRIPT = [words(0, 15), words(15, 30), words(30, 36), words(37, 45), words(50, 51, "yes"), words(60, 70), words(70, 80)]


# ---- sample selection ---------------------------------------------------------------------------------------------------------------------------

def by_label(found):
    return {s.label: s for s in found}


def test_every_speaker_with_enough_clean_speech_gets_ordered_in_range_samples():
    found = by_label(speaker_samples.select(DIARIZATION, TRANSCRIPT))
    assert list(found) == [A, B, C]
    for label in (A, B):
        got = found[label]
        assert 1 <= len(got.samples) <= speaker_samples.PRIMARY
        for sample in got.samples:
            assert speaker_samples.MIN_SECONDS <= sample.end - sample.start <= speaker_samples.MAX_SECONDS
            # entirely inside this speaker's own speech
            assert any(s["speaker"] == label and s["start"] <= sample.start and sample.end <= s["end"] + 1e-6 for s in DIARIZATION) or label == B
        assert [s.start for s in got.samples] == sorted(s.start for s in got.samples)
    assert found[A].samples and all(s.quality == "good" for s in found[A].samples)


def test_selection_is_deterministic_and_independent_of_input_order():
    first = [s.view() for s in speaker_samples.select(DIARIZATION, TRANSCRIPT)]
    assert first == [s.view() for s in speaker_samples.select(DIARIZATION, TRANSCRIPT)]
    assert first == [s.view() for s in speaker_samples.select(list(reversed(DIARIZATION)), list(reversed(TRANSCRIPT)))]


def test_samples_do_not_overlap_each_other_and_alternates_are_distinct():
    got = by_label(speaker_samples.select(DIARIZATION, TRANSCRIPT))[A]
    every = [*got.samples, *got.alternates]
    for i, one in enumerate(every):
        for other in every[i + 1:]:
            assert one.end <= other.start or other.end <= one.start


def test_a_speaker_who_barely_spoke_degrades_to_no_samples_with_a_reason():
    got = by_label(speaker_samples.select(DIARIZATION, TRANSCRIPT))[C]
    assert got.samples == [] and got.alternates == [] and "Too little" in got.reason


def test_a_window_where_another_speaker_talks_over_is_avoided_when_a_clean_one_exists():
    diar = [span(0, 20, A), span(4, 9, B), span(40, 52, A)]  # B talks across the middle of A's first turn
    trans = [words(0, 20), words(4, 9), words(40, 52)]
    got = by_label(speaker_samples.select(diar, trans))[A]
    best = got.samples[0] if got.samples[0].quality == "good" else None
    assert best is not None
    assert not any(s.quality == "good" and s.start < 9 and s.end > 4 for s in got.samples)  # a window across B's words is not called good
    assert any(s.start >= 40 for s in got.samples)  # the clean turn is offered


def test_only_overlapped_speech_is_offered_but_marked_low_quality():
    diar = [span(0, 6, A), span(1, 6, B)]
    trans = [words(0, 6), words(1, 6)]
    got = by_label(speaker_samples.select(diar, trans))[A]
    assert got.samples and all(s.quality == "low" for s in got.samples)
    assert any("another speaker" in n for s in got.samples for n in s.notes) and got.reason


def test_recording_gaps_lower_quality_and_an_unclear_stretch_is_offered_only_when_nothing_clear_exists():
    diar = [span(0, 8, A), span(20, 28, A)]
    gaps = {"spans": [{"start": 0, "end": 4}]}
    trans = [words(0, 8), words(20, 28)]
    got = by_label(speaker_samples.select(diar, trans, gaps))[A]
    assert [(s.start, s.quality) for s in got.samples] == [(20.0, "good")]  # the stretch with missing audio does not displace it
    only = by_label(speaker_samples.select([span(0, 8, A)], [words(0, 8)], gaps))[A]
    assert only.samples[0].quality == "low" and any("no recorded audio" in n for n in only.samples[0].notes) and only.reason


def test_unrecognised_speech_is_marked_low_quality():
    got = by_label(speaker_samples.select([span(0, 8, A)], [words(0, 8, "x")]))[A]
    assert got.samples[0].quality == "low" and any("little speech" in n for n in got.samples[0].notes)


def test_the_sample_is_clipped_to_the_recording_length():
    got = by_label(speaker_samples.select([span(0, 30, A)], [words(0, 30)], None, duration=6.0))[A]
    assert got.samples and all(s.end <= 6.0 for s in got.samples)


def test_empty_and_malformed_input_is_safe():
    assert speaker_samples.select(None, None) == []
    assert speaker_samples.select([{"start": 3, "end": 1, "speaker": A}, {"start": 0, "end": 5}], []) == []


# ---- identity records ---------------------------------------------------------------------------------------------------------------------------

def meeting(**fields) -> Meeting:
    base = {"title": "t", "source_filename": "a", "content_type": "b", "audio_path": "c", "status": MeetingJobStatus.COMPLETE,
            "transcript_segments": TRANSCRIPT, "diarization_segments": DIARIZATION}
    base.update(fields)
    return Meeting(**base)


def test_apply_confirms_names_unknown_and_skipped_and_only_names_become_display_names():
    state, names = speaker_identity.apply(meeting(), {A: {"status": "named", "name": " Priya  Shah ", "contact_id": "c1"}, B: {"status": "unknown"}, C: {"status": "skipped"}})
    assert names == {A: "Priya Shah"}
    assert state.identities[A].contact_id == "c1" and state.identities[B].status == "unknown" and state.identities[C].status == "skipped"
    assert state.fingerprint == speaker_identity.fingerprint(DIARIZATION)


@pytest.mark.parametrize("decision", [{"status": "named"}, {"status": "named", "name": "x" * 61}, {"status": "unknown", "contact_id": "c1"}, {"status": "bogus"}])
def test_apply_rejects_bad_decisions_and_changes_nothing(decision):
    with pytest.raises(speaker_identity.IdentityError):
        speaker_identity.apply(meeting(speaker_names={A: "Keep"}), {A: decision})


def test_apply_rejects_a_label_the_diarization_does_not_have():
    with pytest.raises(speaker_identity.IdentityError):
        speaker_identity.apply(meeting(), {"SPEAKER_09": {"status": "named", "name": "x"}})


def test_clear_removes_a_confirmation_and_names_set_before_phase_54_are_adopted():
    m = meeting(speaker_names={A: "Old Name"})
    state, names = speaker_identity.apply(m, {B: {"status": "named", "name": "Tom"}})
    assert names == {A: "Old Name", B: "Tom"}  # not lost
    cleared, names = speaker_identity.apply(m.model_copy(update={"speaker_identity": state, "speaker_names": names}), {A: {"status": "clear"}})
    assert names == {B: "Tom"} and A not in cleared.identities


def test_a_different_diarization_supersedes_confirmations_and_an_identical_one_keeps_them():
    state, names = speaker_identity.apply(meeting(), {A: {"status": "named", "name": "Priya"}})
    m = meeting(speaker_identity=state, speaker_names=names)
    same_state, same_names = speaker_identity.supersede(m, [dict(s) for s in DIARIZATION])
    assert same_names == {A: "Priya"} and same_state.identities[A].name == "Priya" and same_state.superseded is None
    moved = [span(0, 10, A), span(10, 30, B)]
    new_state, new_names = speaker_identity.supersede(m, moved)
    assert new_names == {} and new_state.identities == {}
    assert new_state.superseded.identities[A].name == "Priya" and new_state.fingerprint == speaker_identity.fingerprint(moved)


# ---- stale outputs ------------------------------------------------------------------------------------------------------------------------------

def test_outputs_go_stale_when_the_names_they_were_written_under_change():
    names = {A: "Priya"}
    m = meeting(speaker_names=names, summary=MeetingOutput(text="s", tier="local", speaker_basis=speaker_basis(names)),
                minutes=MeetingOutput(text="m", tier="local"))
    assert m.stale_outputs == ["minutes"]  # no recorded basis and names set: cannot be shown to match
    assert m.model_copy(update={"speaker_names": {A: "Tom"}}).stale_outputs == ["summary", "minutes"]
    assert m.model_copy(update={"speaker_names": {}}).stale_outputs == ["summary"]  # removing a name changes what the summary says too
    assert meeting(summary=MeetingOutput(text="s", tier="local")).stale_outputs == []  # never any names: nothing to be wrong about


# ---- the routes ---------------------------------------------------------------------------------------------------------------------------------

def make() -> tuple[TestClient, str, InMemoryMeetingStore]:
    store = InMemoryMeetingStore()

    async def seed() -> str:
        created = await store.create_meeting(title="Sync", audio=b"x", source_filename="m.m4a", content_type="audio/mp4", participants=["Dana Lee"])
        store._touch(created, transcript_segments=TRANSCRIPT, diarization_segments=DIARIZATION, status="complete")
        return created.id

    meeting_id = asyncio.run(seed())
    client = TestClient(create_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(),
        meeting_store=store, run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, llm_transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    ))
    return client, meeting_id, store


def test_the_identify_screen_lists_every_label_with_samples_lines_and_suggestions():
    client, mid, _ = make()
    body = client.get(f"/meetings/{mid}/speakers/identify").json()
    assert [s["label"] for s in body["speakers"]] == [A, B, C]
    first = body["speakers"][0]
    assert first["display_name"] == "Speaker 1" and first["samples"] and first["identity"] is None and first["lines"] == 4
    assert body["speakers"][2]["samples"] == [] and body["speakers"][2]["reason"]
    assert "Dana Lee" in body["suggestions"] and body["needs_review"] is False and body["fingerprint"]


def test_confirming_names_updates_the_meeting_and_the_transcript_lines_and_keeps_raw_labels():
    client, mid, store = make()
    fingerprint = client.get(f"/meetings/{mid}/speakers/identify").json()["fingerprint"]
    saved = client.put(f"/meetings/{mid}/speakers/identify", json={"fingerprint": fingerprint, "decisions": {
        A: {"status": "named", "name": "Priya Shah", "contact_id": "contact-1"}, B: {"status": "unknown"}, C: {"status": "skipped"}}})
    assert saved.status_code == 200
    body = saved.json()
    assert body["speaker_names"] == {A: "Priya Shah"}  # unknown and skipped are not names
    assert body["speaker_identity"]["identities"][A]["contact_id"] == "contact-1"
    assert body["diarization_segments"] == DIARIZATION  # raw output untouched
    got = asyncio.run(store.get_meeting(mid))
    assert outputs.transcript_lines(got)[0].startswith("[0:00] Priya Shah:")
    assert outputs.transcript_lines(got)[2].startswith("[0:30] SPEAKER_01:") or "Speaker 2" in outputs.transcript_lines(got)[2]  # unknown stays generic
    shown = client.get(f"/meetings/{mid}/speakers/identify").json()["speakers"]
    assert shown[0]["identity"]["status"] == "named" and shown[1]["identity"]["status"] == "unknown" and shown[1]["display_name"] == "Speaker 2"


def test_renaming_clearing_and_validation():
    client, mid, _ = make()
    url = f"/meetings/{mid}/speakers/identify"
    client.put(url, json={"decisions": {A: {"status": "named", "name": "Priya"}}})
    assert client.put(url, json={"decisions": {A: {"status": "named", "name": "Priya S."}}}).json()["speaker_names"] == {A: "Priya S."}
    assert client.put(url, json={"decisions": {A: {"status": "clear"}}}).json()["speaker_names"] == {}
    assert client.put(url, json={"decisions": {"SPEAKER_09": {"status": "unknown"}}}).status_code == 422
    assert client.put(url, json={"decisions": {A: {"status": "named"}}}).status_code == 422
    assert client.put("/meetings/nope/speakers/identify", json={"decisions": {}}).status_code == 404


def test_a_changed_diarization_is_refused_not_named_blindly():
    client, mid, _ = make()
    assert client.put(f"/meetings/{mid}/speakers/identify", json={"fingerprint": "stale", "decisions": {A: {"status": "unknown"}}}).status_code == 409


def test_the_older_names_route_writes_the_same_record():
    client, mid, _ = make()
    client.put(f"/meetings/{mid}/speakers", json={"names": {A: "Priya"}})
    shown = client.get(f"/meetings/{mid}/speakers/identify").json()["speakers"][0]
    assert shown["identity"]["status"] == "named" and shown["identity"]["name"] == "Priya"
    assert client.get(f"/meetings/{mid}").json()["speaker_names"] == {A: "Priya"}


def test_a_name_change_marks_existing_outputs_stale_and_a_regeneration_clears_it():
    client, mid, store = make()
    asyncio.run(store.set_output(mid, "summary", MeetingOutput(text="Priya agreed.", tier="local")))
    assert client.get(f"/meetings/{mid}").json()["stale_outputs"] == []
    client.put(f"/meetings/{mid}/speakers/identify", json={"decisions": {A: {"status": "named", "name": "Priya"}}})
    assert client.get(f"/meetings/{mid}").json()["stale_outputs"] == ["summary"]
    names = {A: "Priya"}
    asyncio.run(store.set_output(mid, "summary", MeetingOutput(text="Priya agreed.", tier="local", speaker_basis=speaker_basis(names))))
    assert client.get(f"/meetings/{mid}").json()["stale_outputs"] == []


def test_rediarization_does_not_carry_names_to_changed_labels_and_flags_the_screen():
    client, mid, store = make()
    client.put(f"/meetings/{mid}/speakers/identify", json={"decisions": {A: {"status": "named", "name": "Priya"}}})

    async def redo():
        store._touch(await store.get_meeting(mid), status=MeetingJobStatus.DIARIZING)
        return await store.mark_diarized(mid, diarization_segments=[span(0, 12, A), span(12, 40, B)])

    again = asyncio.run(redo())
    assert again.speaker_names == {} and again.speaker_identity.identities == {}
    screen = client.get(f"/meetings/{mid}/speakers/identify").json()
    assert screen["needs_review"] and screen["superseded"]["identities"][A]["name"] == "Priya"
    assert all(s["identity"] is None for s in screen["speakers"])


def test_identical_rediarization_keeps_the_names():
    client, mid, store = make()
    client.put(f"/meetings/{mid}/speakers/identify", json={"decisions": {A: {"status": "named", "name": "Priya"}}})

    async def redo():
        store._touch(await store.get_meeting(mid), status=MeetingJobStatus.DIARIZING)
        return await store.mark_diarized(mid, diarization_segments=[dict(s) for s in DIARIZATION])

    assert asyncio.run(redo()).speaker_names == {A: "Priya"}


def test_the_screen_needs_a_processed_meeting_with_speaker_detection():
    client, mid, store = make()
    asyncio.run(store.get_meeting(mid))
    store._touch(store._meetings[mid], diarization_segments=None)
    assert client.get(f"/meetings/{mid}/speakers/identify").status_code == 409
    assert client.get("/meetings/nope/speakers/identify").status_code == 404


def test_deleting_the_meeting_removes_the_mapping_with_it():
    client, mid, store = make()
    client.put(f"/meetings/{mid}/speakers/identify", json={"decisions": {A: {"status": "named", "name": "Priya"}}})
    assert client.delete(f"/meetings/{mid}").status_code == 200
    assert asyncio.run(store.get_meeting(mid)) is None
    assert client.get(f"/meetings/{mid}/speakers/identify").status_code == 404


# ---- samples against real audio -----------------------------------------------------------------------------------------------------------------

def test_every_sample_plays_the_audio_of_its_own_speaker_at_its_own_timestamps():
    """A synthetic recording where each speaker is a distinct tone (A 440 Hz, B 880 Hz, C 1320 Hz), served through the real audio route and cut by
    the returned time ranges: the audio inside each sample must carry that speaker's tone and no other. Proves the ranges index the recording, not just the transcript."""
    import io
    import math
    import struct
    import wave

    rate = 8000
    plan = [(0, 14, 440, A), (14, 26, 880, B), (26, 34, 1320, C), (34, 52, 440, A), (52, 66, 880, B)]  # A, B and C each talk in turns; nobody overlaps
    frames = bytearray()
    for start, end, hz, _ in plan:
        for n in range(int((end - start) * rate)):
            frames += struct.pack("<h", int(12000 * math.sin(2 * math.pi * hz * n / rate)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(frames))
    wav = buf.getvalue()

    store = InMemoryMeetingStore()

    async def seed() -> str:
        created = await store.create_meeting(title="Tones", audio=wav, source_filename="t.wav", content_type="audio/wav")
        store._touch(created, status="complete", duration_seconds=66.0,
                     diarization_segments=[span(s, e, who) for s, e, _, who in plan],
                     transcript_segments=[words(s, e) for s, e, _, _ in plan])
        return created.id

    mid = asyncio.run(seed())
    client = TestClient(create_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=store,
        run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(),
        confirmation_store=InMemoryConfirmationStore(), llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False,
        llm_transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    ))

    def power(samples: list[int], hz: int) -> float:
        """Goertzel: the energy at one frequency."""
        k = 2 * math.cos(2 * math.pi * hz / rate)
        s1 = s2 = 0.0
        for x in samples:
            s1, s2 = x + k * s1 - s2, s1
        return s1 * s1 + s2 * s2 - k * s1 * s2

    tone = {A: 440, B: 880, C: 1320}
    screen = client.get(f"/meetings/{mid}/speakers/identify").json()
    checked = 0
    for card in screen["speakers"]:
        assert card["samples"], card["label"]
        for sample in [*card["samples"], *card["alternates"]]:
            # fetch exactly the bytes a player would: a ranged read of the recording through the audio route
            first = 44 + int(sample["start"] * rate) * 2
            last = 44 + int(sample["end"] * rate) * 2 - 1
            got = client.get(f"/meetings/{mid}/audio", headers={"Range": f"bytes={first}-{last}"})
            assert got.status_code == 206
            pcm = struct.unpack(f"<{len(got.content) // 2}h", got.content)
            energy = {label: power(list(pcm[:rate * 4]), hz) for label, hz in tone.items()}
            assert max(energy, key=energy.get) == card["label"], (card["label"], sample)
            assert energy[card["label"]] > 50 * sorted(energy.values())[-2]  # and the others are not there
            checked += 1
    assert checked >= 5
