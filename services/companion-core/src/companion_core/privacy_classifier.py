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
