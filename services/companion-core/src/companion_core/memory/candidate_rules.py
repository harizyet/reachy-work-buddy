"""Deterministic memory-candidate rules (Phase 44F; no model, no I/O).

The only input is the owner's own final message. A candidate is proposed only when the WHOLE message is one short owner sentence that a rule covers, so a pasted document, a quoted block, a
list, a URL or an instruction planted inside other text cannot match: the pattern must cover the entire message. A message that looks sensitive, that carries an identifier, that asks for an
action, or that tries to instruct the assistant about its own rules is never proposed (and leaves no trace). Rules are versioned; every candidate records the rule id and version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shared.models.memory import MemoryType

RULESET_VERSION = 1
MAX_CHARS = 400

# Anything that could make a stored sentence sensitive. A hit means no candidate and no row (the caller counts it without recording any text).
_SENSITIVE = re.compile(
    r"\b(?:password|passcode|passphrase|pin\b|pin code|token|api[- ]?key|secret|credential|private key|ssn|social security|passport|licen[sc]e number|credit card|debit card|card number|"
    r"iban|bank|account number|routing number|salary|salaries|payroll|wage|tax|taxes|loan|mortgage|debt|medical|medication|diagnos\w*|prescription|therap\w*|doctor|hospital|illness|disease|"
    r"disorder|allerg\w*|pregnan\w*|surgery|cancer|depress\w*|anxiety|confidential|nda|lawsuit|legal|attorney|lawyer|divorce|immigration|visa|religio\w*|church|mosque|political|"
    r"sexual\w*|gender|orientation|arrest\w*|criminal)\b", re.IGNORECASE)
_IDENTIFIER = re.compile(r"\d{6,}|@|https?://|www\.|[A-Za-z0-9+/]{32,}|\b(?:\d[ -]?){9,}\d\b")
_QUOTE_OR_CODE = re.compile(r"[\"“”`<>\[\]{}]|^\s*[>#*-]\s|\n")
_HEDGE = re.compile(r"\b(?:today|tonight|tomorrow|yesterday|right now|at the moment|currently|this (?:morning|afternoon|evening|week|month|year)|maybe|perhaps|probably|i think|i guess|"
                    r"might|could|would|should|if|unless|whether|when|while|because|but|so that)\b", re.IGNORECASE)
_ACTION = re.compile(r"\b(?:send|email|forward|delete|remove|erase|wipe|transfer|pay|buy|order|purchase|book|grant|authori[sz]e|approve|unlock|disable|enable|turn off|turn on|shut ?down|"
                     r"reply|share|publish|post|install|run|execute|call|text|message)\b", re.IGNORECASE)
_INJECTION = re.compile(r"\b(?:ignore|disregard|forget|override|bypass|reveal|jailbreak|pretend|act as|you are now|system prompt|instructions?|admin mode|developer mode|safety|rules?|"
                        r"previous|above|assistant|system:|prompt|accept\w*|candidate\w*|suggestion\w*|memory|memories|remember|review\w*|auto\w*)\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?](?:\s+|$)")


@dataclass(frozen=True)
class Proposal:
    text: str
    rule_id: str
    rule_version: int
    proposed_type: MemoryType


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalise(text: str) -> str:
    """The form a keyed digest is computed over: case-folded, punctuation removed, spaces collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.casefold())).strip()


def sensitive_hit(text: str) -> bool:
    return bool(_SENSITIVE.search(text))


def shape_ok(text: str) -> bool:
    """Whole-message guard: one short owner sentence, no quoted or structured content, no identifier, not a question, not hedged."""
    if not text or len(text) > MAX_CHARS or "\n" in text.strip() or _QUOTE_OR_CODE.search(text):
        return False
    one = clean(text)
    if one.endswith("?") or _IDENTIFIER.search(one) or _HEDGE.search(one):
        return False
    return len(_SENTENCE_END.findall(one)) <= 1 and sum(1 for _ in re.finditer(r"[.!?]\s+[A-Z]", one)) == 0


_RULES: tuple[tuple[str, re.Pattern, MemoryType], ...] = (
    ("preference.prefer", re.compile(r"^I (?:really |much |generally )?prefer (?P<x>[^.!?]{3,200})[.!]?$", re.IGNORECASE), MemoryType.PROFILE),
    ("habit.always_never", re.compile(r"^I (?:always|never|usually) (?P<x>[^.!?]{3,200})[.!]?$", re.IGNORECASE), MemoryType.PROFILE),
    ("instruction.from_now_on", re.compile(r"^(?:From now on|Going forward|From here on)[, ]+(?P<x>[^.!?]{3,200})[.!]?$", re.IGNORECASE), MemoryType.WORKING),
    ("fact.my_x_is", re.compile(r"^My (?P<what>[a-z][a-z' -]{1,40}?) (?:is|are) (?P<x>[^.!?]{2,160})[.!]?$", re.IGNORECASE), MemoryType.PROFILE),
    ("naming.call_me", re.compile(r"^(?i:(?:please )?call me) (?P<x>[A-Z][\w'-]+(?: [A-Z][\w'-]+)?)[.!]?$"), MemoryType.PROFILE),
)


def extract(message: str) -> Proposal | None:
    """The proposal for an owner message, or None. Pure and deterministic; the caller applies the channel, privacy and rate rules."""
    if not shape_ok(message):
        return None
    one = clean(message)
    if sensitive_hit(one) or _INJECTION.search(one):
        return None
    for rule_id, pattern, kind in _RULES:
        if pattern.match(one):
            if rule_id != "naming.call_me" and _ACTION.search(one):
                return None  # a standing sentence that asks for an action is not a memory ("call me" there is a name, not a phone call)
            text = one if one[-1] in ".!" else one + "."
            return Proposal(text=text, rule_id=rule_id, rule_version=RULESET_VERSION, proposed_type=kind)
    return None
