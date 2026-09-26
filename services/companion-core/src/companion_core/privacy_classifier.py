"""Placeholder privacy classification for a conversation turn.

Real content understanding is Phase 10+'s job (real reasoning replaces the
echo-style placeholder in app.py entirely). Phase 9's exit criterion is
about the *router* (reachy-hub) having final, enforced authority over
routing based on response metadata — it needs companion-core to genuinely
propose that metadata, not fabricate it in a test. This keyword classifier
is that genuine (if simple) proposal: real code, running on the real turn
text, producing a real `Privacy` value reachy-hub then enforces. It is not
meant to be good text classification, just non-fake.
"""

from __future__ import annotations

import re

from shared.models.response import Privacy

_SENSITIVE_KEYWORDS = ("salary", "confidential", "ssn", "social security", "password", "medical")
_WORK_PRIVATE_KEYWORDS = ("calendar", "meeting", "schedule", "email")


def classify_privacy(text: str) -> Privacy:
    lowered = text.lower()
    if any(keyword in lowered for keyword in _SENSITIVE_KEYWORDS):
        return Privacy.SENSITIVE
    if any(keyword in lowered for keyword in _WORK_PRIVATE_KEYWORDS):
        return Privacy.WORK_PRIVATE
    return Privacy.PUBLIC


# Owner decision (2026-09-26, 24e physical run): a work word alone does not
# make a general question private. "How do I schedule a meeting on Outlook?"
# is public; "When is my next meeting?" is not. Sensitive words still count
# anywhere.
_WORK_NOUN = r"(?:calendar|meetings?|schedule|emails?|inbox|agenda|appointments?)"
_OWNER_WORK_RE = re.compile(
    rf"\b(?:my|our)\s+(?:[\w']+\s+){{0,3}}?{_WORK_NOUN}\b"
    rf"|\b(?:today's|tomorrow's|tonight's|this week's)\s+{_WORK_NOUN}\b"
    rf"|\b(?:do|did|will)\s+i\s+have\b.*\b{_WORK_NOUN}\b"
    rf"|\bi(?:'ve| have| had| got)(?:\s+[\w']+){{0,3}}?\s+{_WORK_NOUN}\b"
    r"|\bi(?:'m| am)\s+meeting\b"
    rf"|\b(?:any|anything)\b.*\b{_WORK_NOUN}\b.*\b(?:today|tomorrow|tonight|this (?:morning|afternoon|evening|week))\b"
    rf"|\b(?:new|unread)\s+(?:emails?|messages)\b"
    r"|\b(?:emailed|messaged)\s+me\b"
)


def classify_question_privacy(text: str) -> Privacy:
    """For the generated-reply branch, which labels only the owner's
    question, never the model's wording: private data from tools and memory
    reaches that reply only through the history, whose labels carry
    (ConversationStore.reply_privacy)."""
    lowered = text.lower()
    if any(keyword in lowered for keyword in _SENSITIVE_KEYWORDS):
        return Privacy.SENSITIVE
    if _OWNER_WORK_RE.search(lowered):
        return Privacy.WORK_PRIVATE
    return Privacy.PUBLIC
