"""Phase 25.0/25a.4 request sensitivity classification and authorization
(docs/phase-25.md, ADR 0024)."""

import pytest
from reachy_hub.request_sensitivity import (
    InteractionDecision,
    RequestSensitivity,
    authorize_request,
    classify_sensitivity,
)

from shared.models.session import InteractionMode
from shared.models.trust import TrustLevel


@pytest.mark.parametrize("trust", list(TrustLevel))
@pytest.mark.parametrize("mode", list(InteractionMode))
def test_public_is_always_allowed(trust, mode) -> None:
    assert authorize_request(RequestSensitivity.PUBLIC, trust, mode) == InteractionDecision.ALLOW


@pytest.mark.parametrize("trust", [TrustLevel.T0, TrustLevel.T1])
def test_personal_below_t2_requires_verification(trust) -> None:
    decision = authorize_request(RequestSensitivity.PERSONAL, trust, InteractionMode.DESK)
    assert decision == InteractionDecision.REQUIRE_VERIFICATION


@pytest.mark.parametrize("trust", [TrustLevel.T2, TrustLevel.T3])
def test_personal_at_t2_or_above_is_allowed(trust) -> None:
    decision = authorize_request(RequestSensitivity.PERSONAL, trust, InteractionMode.DESK)
    assert decision == InteractionDecision.ALLOW


@pytest.mark.parametrize("trust", [TrustLevel.T0, TrustLevel.T1])
def test_consequential_below_t2_requires_verification(trust) -> None:
    decision = authorize_request(RequestSensitivity.CONSEQUENTIAL, trust, InteractionMode.DESK)
    assert decision == InteractionDecision.REQUIRE_VERIFICATION


def test_consequential_at_t2_reaches_core_but_core_still_gates_further() -> None:
    # This authorizer only decides whether the transcript may reach Core;
    # ADR 0011's confirmation/bulk-block policy is a separate, later gate.
    decision = authorize_request(RequestSensitivity.CONSEQUENTIAL, TrustLevel.T2, InteractionMode.DESK)
    assert decision == InteractionDecision.ALLOW


@pytest.mark.parametrize("trust", list(TrustLevel))
def test_unknown_sensitivity_always_fails_upward_never_allow(trust) -> None:
    decision = authorize_request(RequestSensitivity.UNKNOWN, trust, InteractionMode.DESK)
    assert decision != InteractionDecision.ALLOW


@pytest.mark.parametrize(
    ("sensitivity", "trust"),
    [
        (RequestSensitivity.PERSONAL, TrustLevel.T1),
        (RequestSensitivity.CONSEQUENTIAL, TrustLevel.T1),
        (RequestSensitivity.UNKNOWN, TrustLevel.T2),
    ],
)
def test_trusted_interaction_mode_does_not_bypass_identity_or_action_policy(sensitivity, trust) -> None:
    trusted = authorize_request(sensitivity, trust, InteractionMode.TRUSTED)
    desk = authorize_request(sensitivity, trust, InteractionMode.DESK)
    assert trusted == desk


@pytest.mark.parametrize(
    "transcript",
    [
        "What time is it?",
        "what's the weather today",
        "What's the weather like tomorrow",
        "Tell me a joke",
    ],
)
def test_classify_recognizes_obvious_public_phrasings(transcript) -> None:
    assert classify_sensitivity(transcript) == RequestSensitivity.PUBLIC


@pytest.mark.parametrize(
    "transcript",
    [
        "What's my next appointment?",
        "Read my email",
        "Check my calendar",
        "What's in my notes",
    ],
)
def test_classify_recognizes_obvious_personal_phrasings(transcript) -> None:
    assert classify_sensitivity(transcript) == RequestSensitivity.PERSONAL


@pytest.mark.parametrize(
    "transcript",
    [
        "Send this email",
        "Delete my calendar event",
        "Cancel my meeting with Alice",
        "Schedule a meeting for tomorrow",
    ],
)
def test_classify_recognizes_obvious_consequential_phrasings(transcript) -> None:
    assert classify_sensitivity(transcript) == RequestSensitivity.CONSEQUENTIAL


@pytest.mark.parametrize(
    "transcript",
    ["", "   ", "How tall is Mount Everest?", "Tell me about the history of Rome", "hmm"],
)
def test_classify_fails_upward_to_unknown_for_anything_not_recognized(transcript) -> None:
    # Deliberately conservative (docs/phase-25.md): no LLM-assist layer
    # exists yet, so an ordinary open-ended question that isn't one of the
    # recognized public phrasings is UNKNOWN, not PUBLIC.
    assert classify_sensitivity(transcript) == RequestSensitivity.UNKNOWN


def test_classify_prefers_consequential_over_a_public_looking_prefix() -> None:
    transcript = "What time is it, then delete my calendar event"
    assert classify_sensitivity(transcript) == RequestSensitivity.CONSEQUENTIAL
