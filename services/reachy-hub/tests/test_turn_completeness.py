"""Phase 24e adaptive end of turn: the deterministic completeness rules.

Shapes follow the 24d transcripts (no personal content). STT punctuation is
tested both missing and spurious, since faster-whisper adds a final period
to segments the speaker trailed off.
"""

from __future__ import annotations

import pytest
from reachy_hub.turn_completeness import looks_complete


@pytest.mark.parametrize(
    "text",
    [
        "I was wondering if you could tell me",
        "I was wondering if you could tell me.",
        "I was wondering",
        "So I went to the",
        "So I went to the.",
        "I need to buy milk and",
        "I need to buy milk and.",
        "Remind me about",
        "Remind me about.",
        "I want to talk to you about the weather because",
        "It's more expensive than",
        "The thing is",
        "I think",
        "Can you show me",
        "What I meant was...",
        "What I meant was…",
        "Well,",
        "My plan is:",
        "um",
        "Tell me about, uh",
        "and my",
    ],
)
def test_unfinished_segments_are_held(text: str) -> None:
    assert not looks_complete(text)


@pytest.mark.parametrize(
    "text",
    [
        # Finished thoughts, with and without STT punctuation.
        "What's the weather like today?",
        "What's the weather like today",
        "Tell me a joke.",
        "tell me a joke",
        "My code word is pineapple",
        "My code word is pineapple.",
        "Goodbye for now.",
        "Thanks",
        "Who are you?",
        "Turn the lights on.",
        "Log me in",
        # A question may end on a preposition.
        "Who are you talking to?",
        "What is it like?",
        "What are you made of?",
        # Nothing to hold.
        "",
        "   ",
        "?",
    ],
)
def test_finished_segments_are_answered(text: str) -> None:
    assert looks_complete(text)


def test_terminal_punctuation_does_not_override_an_unfinished_ending() -> None:
    for mark in (".", "!", "?"):
        assert not looks_complete(f"I was wondering if you could tell me{mark}")
        assert not looks_complete(f"I need milk and{mark}")
    # Only a question mark finishes a trailing preposition.
    assert not looks_complete("What are you talking about.")
    assert looks_complete("What are you talking about?")
