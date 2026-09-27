"""Phase 24g wake relevance rules (ADR 0023 wake-started sessions)."""

import pytest
from reachy_hub.wake_relevance import assess


@pytest.mark.parametrize(
    ("transcript", "request_text"),
    [
        ("Hey Reachy, what time is it?", "What time is it?"),
        ("Hey Richie. Turn on the lights.", "Turn on the lights."),
        ("Okay, hey Reachy, what's the weather tomorrow?", "What's the weather tomorrow?"),
        ("Reachy, remind me to call mum.", "Remind me to call mum."),
    ],
)
def test_addressed_requests_are_admitted_without_the_wake_phrase(transcript, request_text) -> None:
    result = assess(transcript)
    assert (result.admitted, result.request) == (True, request_text)


@pytest.mark.parametrize(
    ("transcript", "reason"),
    [
        ("", "no_speech"),
        ("...", "no_speech"),
        ("So I told him the meeting moved to Thursday.", "no_wake_phrase"),
        ("I think we should ask Reachy later about it.", "no_wake_phrase"),
        ("Hey Reachy.", "no_request"),
        ("Hey Reachy, um, hmm.", "filler_only"),
        ("Hey Reachy and then he said no.", "continuation"),
    ],
)
def test_unaddressed_or_empty_candidates_are_rejected(transcript, reason) -> None:
    result = assess(transcript)
    assert (result.admitted, result.reason, result.request) == (False, reason, "")
