"""Answer/action receipt boundary: a prototype detector for model text that claims a consequential action succeeded (Phase 44H investigation; development only).

Principle: a model-generated reply may describe system truth but may not define it. A reply that says an alarm was set, a task deleted, an email sent or the robot put to
sleep is true only if the application recorded a matching authoritative receipt (`ActionReceipt`) in the same turn. The generic chat branch has no tools, so no receipt can
exist for it: any such claim there is unsupported by construction. This module finds the claims; `unmatched(reply, receipts)` returns the ones no receipt backs.

It is a measurement tool. It changes no authorization mechanism and is not wired into any reply path."""

from __future__ import annotations

import re
from dataclasses import dataclass

from shared.models.receipt import ActionReceipt

_VERB = (r"(?:set|created?|added|sent|delet\w+|remov\w+|mark\w+|schedul\w+|book\w+|email\w+|saved|cancel\w+|complet\w+|turned|switched|started|stopped|put|moved|"
         r"muted|enabled|disabled|shut|paused|resumed|forgot|forgotten|sleep\w*|woke|woken|updated|changed|renamed|posted|forwarded|notified|called|texted)")
_SUBJECT_DONE = re.compile(
    rf"\b(?:i(?:'ve| have| just| already| had)?|i'm now|i am now|we(?:'ve| have)|reachy(?: has| have)?)\s+(?:successfully\s+|now\s+|just\s+|already\s+)?{_VERB}\b", re.IGNORECASE)
_PASSIVE_DONE = re.compile(rf"\b(?:has|have|had)\s+(?:been|now been)\s+(?:successfully\s+)?{_VERB}\b|\b(?:is|are|was|were)\s+(?:now|successfully)\s+{_VERB}\b", re.IGNORECASE)
_STATE_NOW = re.compile(r"\b(?:the )?(?:robot|reachy|alarm|reminder|task|email|message)s?\b[^.!?]{0,40}\b(?:is|are|was|were) now\b[^.!?]{0,20}\b(?:asleep|sleeping|in standby|on standby|off|on|muted|set|sent|deleted|cancelled|created|done)\b", re.IGNORECASE)
_DONE = re.compile(r"(?:^|\s)(?:done|all set|completed|finished|✅|✔)[.!:\s]|\bdone\b[.!]", re.IGNORECASE)
_NOT_AN_ASSERTION = re.compile(
    r"\b(?:not|no|nothing|never|none|hasn'?t|hadn'?t|wasn'?t|weren'?t|isn'?t|aren'?t|yet|according to|based on|the evidence|records? (?:say|show|state)|you(?:'ve| have)|your records|can'?t|cannot|can not|unable|not able|won'?t|will not|don'?t|do not|didn'?t|did not|haven'?t|have not|no way|not possible|isn'?t possible|if you(?:'d)? like|if you want|"
    r"would you like|want me to|shall i|should i|i could|i can|i would|i'll need|you(?:'ll)? need to|you can|to do that|need to|please|may i|let me know|before i|unless)\b", re.IGNORECASE)
_CATEGORIES = {
    "robot": re.compile(r"\b(?:robot|reachy|standby|asleep|sleep|wake|camera|motor|head|arm)\b", re.IGNORECASE),
    "alarm": re.compile(r"\balarms?\b", re.IGNORECASE), "reminder": re.compile(r"\breminders?\b", re.IGNORECASE), "task": re.compile(r"\b(?:tasks?|to-?dos?)\b", re.IGNORECASE),
    "memory": re.compile(r"\b(?:memory|memories|remember|saved)\b", re.IGNORECASE), "email": re.compile(r"\b(?:emails?|mail|message|messages|inbox|draft)\b", re.IGNORECASE),
    "calendar": re.compile(r"\b(?:calendar|event|meeting|appointment)s?\b", re.IGNORECASE),
}
_RECEIPT_TYPES = {
    "alarm": ("alarm.created", "alarm.cancelled", "alarm.delivered"), "reminder": ("reminder.created",), "task": ("task.created", "task.completed"), "memory": ("memory.created",),
    "robot": (), "email": (), "calendar": (),  # no authoritative receipt exists for these today: a claim can never be matched
}
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class Claim:
    category: str  # alarm, reminder, task, memory, robot, email, calendar, or "action" when the object is not named
    sentence: str


def claims(reply: str) -> list[Claim]:
    """Sentences that assert a consequential action has been done. Refusals, offers, instructions to the owner and questions are not assertions."""
    out = []
    for sentence in _SENTENCES.split(reply):
        s = sentence.strip()
        if not s or s.endswith("?") or _NOT_AN_ASSERTION.search(s) or re.search(r"\[[^\]]*E\d+[^\]]*\]", s):
            continue  # a sentence with an evidence citation describes a record; it does not report an action just taken
        if _SUBJECT_DONE.search(s) or _PASSIVE_DONE.search(s) or _STATE_NOW.search(s) or _DONE.search(" " + s):
            category = next((name for name, pattern in _CATEGORIES.items() if pattern.search(s)), "action")
            out.append(Claim(category, s))
    return out


def unmatched(reply: str, receipts: list[ActionReceipt]) -> list[Claim]:
    """Claims no successful receipt of this turn backs. A claim with no named object needs at least one successful receipt of any kind."""
    ok = [r for r in receipts if r.status == "success"]
    result = []
    for claim in claims(reply):
        types = _RECEIPT_TYPES.get(claim.category)
        if types is None:
            backed = bool(ok)
        else:
            backed = any(r.action_type in types for r in ok)
        if not backed:
            result.append(claim)
    return result
