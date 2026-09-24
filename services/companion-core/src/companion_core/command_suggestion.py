"""Natural-language command-suggestion classifier (Phase 24b,
docs/phase-24b.md). Understanding intent and authorizing an action are
separate responsibilities: this module only ever produces a *suggestion*
— a recognized intent never itself calls a hub/robot action. Only
companion_core/commands/parser.py's explicit `/reachy <action>` parser
may do that.

This retires robot_power_intent.py's substring matching entirely rather
than repurposing it as this classifier: reusing that matcher would keep
its exact false-positive (e.g. "How do I turn off Reachy?" would still
produce a wrong suggestion instead of a plain answer), just downgraded
from actuation to a wrong suggestion. This is a separate implementation
that distinguishes requests from questions, negations, hypotheticals and
reported speech via the model's own `speech_act` classification.

Fail-closed: any classifier unavailability, timeout, malformed/non-schema
response, or missing/unrecognized `speech_act`/`confidence` is treated
identically to a non-"request" speech act — no suggestion, and the
failure is never surfaced to the user. The ordinary conversational branch
proceeds exactly as if this module were never called.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from companion_core.llm.client import ProviderUnavailable
from companion_core.llm.router import route_completion
from shared.models.command_suggestion import Intent, SpeechAct, SuggestionResult
from shared.models.llm import LLMConfig

# A suggestion is only offered above this confidence — deliberately a
# fixed threshold, not a knob to tune toward eventually treating
# suggestions as authoritative (docs/phase-24b.md Non-goals).
CONFIDENCE_THRESHOLD = 0.75

# Cheap, deliberately over-inclusive gate on whether it's even worth
# spending an LLM call on classification — it only decides whether the
# classifier runs, never what it concludes, so false positives just cost
# an extra fail-closed call and false negatives are the actual risk this
# phase cares about avoiding. Every one of docs/phase-24b.md's exit
# criteria examples mentions "reachy" by name, same as the retired
# matcher's phrase lists did.
_PLAUSIBLY_ROBOT_RELATED = "reachy"

_SYSTEM_PROMPT = """You are a strict intent classifier for a home robot assistant named Reachy. \
Given the user's message, respond with ONLY a single JSON object (no prose, no markdown \
fences) of this exact shape:

{"intent": "robot_standby" | "robot_resume" | "none", "speech_act": "request" | "question" | \
"negation" | "hypothetical" | "statement" | "other", "confidence": <number between 0 and 1>}

Rules:
- intent "robot_standby": the message is about putting Reachy into standby, turning it off, \
or shutting it down.
- intent "robot_resume": the message is about waking Reachy up, turning it on, or resuming it.
- intent "none": neither of the above.
- speech_act "request" ONLY when the user is directly asking the assistant to perform that \
action right now, e.g. "Could you put Reachy to sleep?" or "Turn Reachy off please."
- speech_act "question" for questions about how/why/whether to do it, e.g. "How do I turn off \
Reachy?" or "Is it safe to wake Reachy up?"
- speech_act "negation" for messages that explicitly do not want the action, e.g. "Don't turn \
off Reachy" or "I don't want to wake Reachy up."
- speech_act "hypothetical" for conditional or what-if phrasing, e.g. "What happens if I turn \
off Reachy?"
- speech_act "statement" for reported, quoted, or third-party statements about the action.
- speech_act "other" for anything else.
- confidence: your confidence in this classification, from 0.0 to 1.0.

Respond with the JSON object only, nothing else."""

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

# The classifier's own calls are internal QoL telemetry, not user-facing
# assistant answers — kept out of the operator-visible LLM usage ledger
# rather than mixed into it.
class _DiscardingUsageStore:
    async def append(self, entry) -> None:
        return None


def _plausibly_actionable(text: str) -> bool:
    return _PLAUSIBLY_ROBOT_RELATED in text.lower()


def _parse(raw: str) -> SuggestionResult | None:
    match = _JSON_OBJECT.search(raw)
    if match is None:
        return None
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return None
    try:
        return SuggestionResult.model_validate(payload)
    except ValidationError:
        return None


async def classify(text: str, config: LLMConfig, *, transport=None) -> SuggestionResult | None:
    """Returns a SuggestionResult only when the classifier itself judged
    the message an actionable, high-confidence request; otherwise returns
    None uniformly, whether that's because the classifier failed, timed
    out, returned unparseable output, or genuinely resolved the message
    to a non-"request" speech act — callers must not distinguish these
    (docs/phase-24b.md exit criteria: verified by call-count/output
    assertions, not by inspecting classifier internals)."""
    if not _plausibly_actionable(text):
        return None
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    try:
        raw = await route_completion(config, messages, _DiscardingUsageStore(), transport=transport)
    except ProviderUnavailable:
        return None
    result = _parse(raw)
    if result is None:
        return None
    if result.speech_act != SpeechAct.REQUEST or result.intent == Intent.NONE:
        return None
    if result.confidence < CONFIDENCE_THRESHOLD:
        return None
    return result


_SUGGESTION_LABELS: dict[Intent, tuple[str, str]] = {
    Intent.ROBOT_STANDBY: ("put Reachy into standby", "/reachy standby"),
    Intent.ROBOT_RESUME: ("wake Reachy up", "/reachy wake"),
}


def format_suggestion_reply(intent: Intent) -> str:
    label, command = _SUGGESTION_LABELS[intent]
    return f"It sounds like you want to {label}. Use {command}."
