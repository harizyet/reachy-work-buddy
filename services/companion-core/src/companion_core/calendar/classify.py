"""Deterministic event classification (ADR 0035). No model and no network: the same facts and rules always give the same answer.

`EventFacts` is what the parser keeps of one occurrence (never a description, and for a hidden event nothing but its time). `classify` turns facts into one class, how sure
the source made it (`explicit` signals in the data, a configurable `rule` over words, or the `owner`'s override) and the reason codes. `reminder_decision` says whether a recording
reminder is created. Neither invents anything: an event that matches nothing is `unknown_timed`, not a guess at a meeting.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class EventClass(StrEnum):
    MEETING = "meeting"
    PERSONAL_APPOINTMENT = "personal_appointment"
    LEAVE_OR_OOO = "leave_or_ooo"
    ALL_DAY = "all_day"
    UNKNOWN_TIMED = "unknown_timed"
    BUSY_PRIVATE = "busy_private"


class Basis(StrEnum):
    EXPLICIT = "explicit"  # a field of the event says so (DTSTART value type, attendees, conferencing, out-of-office status, hidden details)
    RULE = "rule"  # a configurable word list matched the title or categories
    OWNER = "owner"  # the owner overrode it


LEAD_MINUTES_DEFAULT = 5

DEFAULT_LEAVE_KEYWORDS = (
    "out of office", "ooo", "annual leave", "sick leave", "medical leave", "maternity leave", "paternity leave", "parental leave",
    "compassionate leave", "unpaid leave", "on leave", "leave", "vacation", "holiday", "public holiday", "bank holiday", "pto", "day off", "days off", "time off", "off sick",
)
DEFAULT_PERSONAL_KEYWORDS = (
    "dentist", "dental", "doctor", "gp appointment", "clinic", "physio", "physiotherapy", "optician", "haircut", "barber", "personal", "birthday", "school pickup",
    "school run", "gym", "medical", "therapy", "vet",
)
DEFAULT_MEETING_KEYWORDS = (
    "meeting", "sync", "stand-up", "standup", "1:1", "1-1", "one-on-one", "catch-up", "catch up", "review", "retro", "retrospective", "planning", "workshop", "interview",
    "call", "demo", "kickoff", "kick-off", "huddle", "townhall", "town hall", "all hands", "all-hands",
)
# Hosts and markers that make an event a conference even when nothing else says so. Matched against the location and the description at parse time; the text is not kept.
CONFERENCE_MARKERS = (
    "zoom.us", "meet.google.com", "teams.microsoft.com", "teams.live.com", "webex.com", "gotomeeting.com", "goto.com/meeting", "whereby.com", "bluejeans.com", "chime.aws",
    "meet.jit.si", "around.co", "slack.com/huddle",
)
# Titles a free/busy-only publisher uses in place of the real one. They are treated as hidden details, not as a title the owner chose.
REDACTED_TITLES = frozenset({"busy", "private", "private appointment", "busy (private)"})


class EventFacts(BaseModel):
    """What the parser kept of one occurrence. Stored in the snapshot; the rules are applied when it is read, so changing a rule needs no new download."""

    key: str
    series_key: str
    source_uid: str
    start: datetime
    end: datetime
    all_day: bool
    title: str | None = None
    location: str | None = None
    status: str = "confirmed"
    transparent: bool = False  # TRANSP:TRANSPARENT: shown as free
    busy_status: str | None = None  # X-MICROSOFT-CDO-BUSYSTATUS: BUSY | FREE | TENTATIVE | OOF
    categories: list[str] = Field(default_factory=list)
    attendees: list[str] = Field(default_factory=list)  # lower-case addresses of people (not rooms or resources); never returned by the API
    organizer: str | None = None
    owner_response: str | None = None  # the PARTSTAT of the attendee who is the owner, when the owner's address is known
    conference: bool = False
    redacted: bool = False
    recurring: bool = False
    sequence: int = 0
    revision: str = ""  # changes whenever anything the owner sees about this occurrence changes


class ClassificationRules(BaseModel):
    """Owner-configurable rules; every field has a default so an unconfigured install behaves the same way every time."""

    owner_emails: list[str] = Field(default_factory=list, max_length=10)  # lets the classifier tell the owner from other attendees, and read the owner's own answer
    leave_keywords: list[str] = Field(default_factory=lambda: list(DEFAULT_LEAVE_KEYWORDS), max_length=200)
    personal_keywords: list[str] = Field(default_factory=lambda: list(DEFAULT_PERSONAL_KEYWORDS), max_length=200)
    meeting_keywords: list[str] = Field(default_factory=lambda: list(DEFAULT_MEETING_KEYWORDS), max_length=200)
    remind_keyword_meetings: bool = True  # a meeting found only by a title word still gets a reminder; false means only attendee or conferencing evidence does
    leave_suppresses_meetings: bool = False  # off by default: a leave day does not silence meetings scheduled on it


class Classification(BaseModel):
    event_class: EventClass
    basis: Basis
    reasons: list[str]


_NON_WORD = re.compile(r"[^\w:+\-/']+", re.UNICODE)


def _words(text: str) -> str:
    return " " + _NON_WORD.sub(" ", text.lower()).strip() + " "


def _matches(text: str, keywords: list[str]) -> str | None:
    """The first keyword found as whole words, so 'leave' never matches 'leaving' and 'sync' never matches 'asynchronous'."""
    haystack = _words(text)
    for keyword in keywords:
        needle = _words(keyword)
        if needle.strip() and needle in haystack:
            return keyword
    return None


def _owner_set(rules: ClassificationRules) -> set[str]:
    return {address.strip().lower() for address in rules.owner_emails if address.strip()}


def other_attendees(facts: EventFacts, rules: ClassificationRules) -> int:
    """People invited besides the owner. Without the owner's address a single attendee may be the owner, so one is not counted as evidence of a meeting."""
    owners = _owner_set(rules)
    total = len(set(facts.attendees))
    if owners:
        return len([a for a in set(facts.attendees) if a not in owners])
    return total if total >= 2 else 0


def classify(facts: EventFacts, rules: ClassificationRules) -> Classification:
    if facts.redacted:
        return Classification(event_class=EventClass.BUSY_PRIVATE, basis=Basis.EXPLICIT, reasons=["details_hidden"])
    others = other_attendees(facts, rules)
    organizer_is_other = bool(facts.organizer and _owner_set(rules) and facts.organizer not in _owner_set(rules))
    has_meeting_evidence = others > 0 or facts.conference or organizer_is_other
    text = " ".join([facts.title or "", *facts.categories])

    # Leave first: an out-of-office status is explicit, and a leave word is trusted unless the event is plainly a meeting ("Holiday planning" with guests and a call link).
    if (facts.busy_status or "").upper() == "OOF":
        return Classification(event_class=EventClass.LEAVE_OR_OOO, basis=Basis.EXPLICIT, reasons=["busy_status_oof"])
    if not has_meeting_evidence and (hit := _matches(text, rules.leave_keywords)):
        return Classification(event_class=EventClass.LEAVE_OR_OOO, basis=Basis.RULE, reasons=[f"leave_keyword:{hit}"])

    # The value type decides, not the length: a timed event of 24 hours is still timed, and an all-day event can span several days.
    if facts.all_day:
        return Classification(event_class=EventClass.ALL_DAY, basis=Basis.EXPLICIT, reasons=["date_value"])

    reasons = []
    if others > 0:
        reasons.append("attendees")
    if facts.conference:
        reasons.append("conference")
    if organizer_is_other:
        reasons.append("invited_by_other")
    if reasons:
        return Classification(event_class=EventClass.MEETING, basis=Basis.EXPLICIT, reasons=reasons)
    if hit := _matches(text, rules.personal_keywords):
        return Classification(event_class=EventClass.PERSONAL_APPOINTMENT, basis=Basis.RULE, reasons=[f"personal_keyword:{hit}"])
    if hit := _matches(text, rules.meeting_keywords):
        return Classification(event_class=EventClass.MEETING, basis=Basis.RULE, reasons=[f"meeting_keyword:{hit}"])
    return Classification(event_class=EventClass.UNKNOWN_TIMED, basis=Basis.RULE, reasons=["no_signal"])


def apply_override(classification: Classification, override: str | None) -> Classification:
    if not override:
        return classification
    try:
        chosen = EventClass(override)
    except ValueError:
        return classification
    return Classification(event_class=chosen, basis=Basis.OWNER, reasons=["owner_override"])


def reminder_decision(
    facts: EventFacts, classification: Classification, rules: ClassificationRules, leave_periods: list[tuple[datetime, datetime]]
) -> str | None:
    """None when a recording reminder is created; otherwise a fixed code saying why not. A cancelled, declined, all-day, leave, personal or unidentified event never gets one."""
    if facts.status == "cancelled":
        return "cancelled"
    if facts.owner_response == "declined":
        return "declined"
    if facts.all_day and classification.basis is not Basis.OWNER:
        return "all_day"
    if classification.event_class is not EventClass.MEETING:
        return f"not_a_meeting:{classification.event_class.value}"
    if facts.all_day:
        return "all_day"
    if classification.basis is Basis.RULE and not rules.remind_keyword_meetings:
        return "unconfirmed_meeting"
    if rules.leave_suppresses_meetings and any(facts.start < end and facts.end > start for start, end in leave_periods):
        return "on_leave"
    return None
