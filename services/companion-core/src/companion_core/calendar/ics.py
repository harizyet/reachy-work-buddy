"""iCalendar parsing for the read-only feed (ADR 0035). The syntax, recurrence rules, exceptions and time zones are the work of the `icalendar` and
`recurring-ical-events` libraries; this module only turns what they return into `EventFacts`.

Privacy: a description is read to look for a conferencing link and then dropped. A private, confidential or free/busy-only occurrence keeps its time and nothing else. Nothing
here logs an event, and an error carries a fixed code, never text from the feed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo

import icalendar
import recurring_ical_events

from companion_core.calendar.classify import (
    CONFERENCE_MARKERS,
    REDACTED_TITLES,
    EventFacts,
)

MAX_ATTENDEES = 50
_CONFERENCE_PROPS = (
    "CONFERENCE", "X-GOOGLE-CONFERENCE", "X-MICROSOFT-ONLINEMEETINGCONFLINK", "X-MICROSOFT-ONLINEMEETINGEXTERNALLINK", "X-MICROSOFT-SKYPETEAMSMEETINGURL",
)
_PEOPLE = {"INDIVIDUAL", "UNKNOWN", ""}


class FeedError(Exception):
    """A failure with a fixed code (see safe_fetch). The message is the code; nothing from the feed or its URL is ever put in one."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class ParsedFeed:
    facts: list[EventFacts] = field(default_factory=list)
    truncated: bool = False
    skipped: int = 0


def _hash(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:length]


def _address(value) -> str:
    text = str(value).strip().lower()
    return text.removeprefix("mailto:").strip()


def _as_datetime(value: date | datetime, tz: tzinfo) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)
    return datetime(value.year, value.month, value.day, tzinfo=tz)


def _token(value: date | datetime, tz: tzinfo) -> str:
    if isinstance(value, datetime):
        return _as_datetime(value, tz).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return value.strftime("%Y%m%d")


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text(component, name: str) -> str | None:
    value = component.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _has_conference(component, location: str | None) -> bool:
    if any(component.get(name) for name in _CONFERENCE_PROPS):
        return True
    if str(component.get("X-MICROSOFT-ISONLINEMEETING", "")).upper() == "TRUE":
        return True
    haystack = " ".join(filter(None, [location, _text(component, "DESCRIPTION"), _text(component, "URL")])).lower()
    return any(marker in haystack for marker in CONFERENCE_MARKERS)


def _facts(component, tz: tzinfo, owners: set[str], recurring_uids: set[str], cancel_all: bool) -> EventFacts:
    raw_start = component["DTSTART"].dt
    all_day = not isinstance(raw_start, datetime)  # the value type decides: DATE is all-day, DATE-TIME is timed, whatever the length
    start = _as_datetime(raw_start, tz)
    raw_end = component.end
    end = _as_datetime(raw_end, tz) if raw_end is not None else start
    if all_day:
        # DTEND of an all-day event is exclusive (RFC 5545 3.6.1): 19 to 22 October is the 19th, 20th and 21st. A missing or backwards end is one day.
        if raw_end is None or end <= start:
            end = start + timedelta(days=1)
    elif end < start:
        end = start

    uid = _text(component, "UID") or ("nouid:" + _hash(str(component.get("SUMMARY", "")) + _token(raw_start, tz)))
    series = f"ics:{_hash(uid)}"
    recurring = uid in recurring_uids
    token = _token(component["RECURRENCE-ID"].dt, tz) if recurring and component.get("RECURRENCE-ID") is not None else "0"
    key = f"{series}:{token}"

    status = (_text(component, "STATUS") or "").upper()
    state = "cancelled" if cancel_all or status == "CANCELLED" else "tentative" if status == "TENTATIVE" else "confirmed"
    title = _text(component, "SUMMARY")
    event_class = (_text(component, "CLASS") or "").upper()
    redacted = event_class in {"PRIVATE", "CONFIDENTIAL"} or (title is not None and title.casefold() in REDACTED_TITLES)
    transparent = (_text(component, "TRANSP") or "").upper() == "TRANSPARENT"
    sequence = int(component.get("SEQUENCE", 0) or 0)
    base = {"key": key, "series_key": series, "source_uid": uid, "start": start, "end": end, "all_day": all_day, "status": state, "transparent": transparent, "recurring": recurring, "sequence": sequence}

    if redacted:
        facts = EventFacts(**base, redacted=True)
    else:
        location = _text(component, "LOCATION")
        people, owner_response = [], None
        for attendee in _as_list(component.get("ATTENDEE")):
            address = _address(attendee)
            if (str(attendee.params.get("CUTYPE", "")).upper() if hasattr(attendee, "params") else "") not in _PEOPLE:
                continue  # rooms and resources are not people
            people.append(address)
            if address in owners:
                owner_response = str(attendee.params.get("PARTSTAT", "")).lower() or None
        categories = []
        for group in _as_list(component.get("CATEGORIES")):
            categories.extend(str(c).strip() for c in getattr(group, "cats", [group]) if str(c).strip())
        organizer = _address(component["ORGANIZER"]) if component.get("ORGANIZER") else None
        busy = _text(component, "X-MICROSOFT-CDO-BUSYSTATUS") or _text(component, "X-MICROSOFT-CDO-INTENDEDSTATUS")
        facts = EventFacts(
            **base, title=title, location=location, busy_status=busy.upper() if busy else None, categories=categories[:20],
            attendees=sorted(set(people))[:MAX_ATTENDEES], organizer=organizer, owner_response=owner_response, conference=_has_conference(component, location),
        )
    facts.revision = _hash("|".join(map(str, (facts.start.isoformat(), facts.end.isoformat(), facts.title, facts.location, facts.status, facts.all_day, facts.sequence, facts.redacted))), 12)
    return facts


def _free_busy(calendar, window_start: datetime, window_end: datetime, tz: tzinfo) -> list[EventFacts]:
    out = []
    for block in calendar.walk("VFREEBUSY"):
        for prop in _as_list(block.get("FREEBUSY")):
            if str(getattr(prop, "params", {}).get("FBTYPE", "BUSY")).upper() == "FREE":
                continue
            for period in _as_list(getattr(prop, "dt", None)) if not isinstance(getattr(prop, "dt", None), tuple) else [prop.dt]:
                start, end = period
                start = _as_datetime(start, tz)
                end = start + end if isinstance(end, timedelta) else _as_datetime(end, tz)
                if end <= window_start or start >= window_end:
                    continue
                series = "ics:freebusy"
                out.append(EventFacts(
                    key=f"{series}:{start.astimezone(UTC):%Y%m%dT%H%M%SZ}", series_key=series, source_uid="freebusy", start=start, end=end, all_day=False, redacted=True,
                    revision=_hash(f"{start.isoformat()}|{end.isoformat()}", 12),
                ))
    return out


def parse_feed(data: bytes, *, window_start: datetime, window_end: datetime, tz: tzinfo, owner_emails: set[str] | frozenset[str] = frozenset(), max_events: int = 5000) -> ParsedFeed:
    """Every occurrence overlapping [window_start, window_end), recurrences expanded, exceptions applied, cancelled occurrences kept (marked) so a cancellation can be seen as one."""
    try:
        calendar = icalendar.Calendar.from_ical(data)
    except Exception:  # noqa: BLE001 - the library raises several types for malformed input; none is allowed to reach a log with feed text in it
        raise FeedError("not_calendar") from None
    if not isinstance(calendar, icalendar.Calendar):
        raise FeedError("not_calendar")
    owners = {address.strip().lower() for address in owner_emails}
    cancel_all = str(calendar.get("METHOD", "")).upper() == "CANCEL"
    result = ParsedFeed()
    for component in list(calendar.subcomponents):
        if component.name == "VEVENT" and component.get("DTSTART") is None:
            calendar.subcomponents.remove(component)  # the expansion library rejects the whole calendar over one of these, so it is dropped and counted
            result.skipped += 1
    recurring_uids = set()
    for component in calendar.walk("VEVENT"):
        if component.get("RRULE") or component.get("RDATE") or component.get("RECURRENCE-ID"):
            recurring_uids.add(_text(component, "UID") or "")
    try:
        occurrences = recurring_ical_events.of(calendar, components=("VEVENT",), skip_bad_series=True).between(window_start, window_end)
    except Exception:  # noqa: BLE001 - see above
        raise FeedError("parse_failed") from None
    for component in occurrences:
        try:
            result.facts.append(_facts(component, tz, owners, recurring_uids, cancel_all))
        except Exception:  # noqa: BLE001 - one malformed event is skipped and counted, never fatal and never logged with its text
            result.skipped += 1
    try:
        result.facts.extend(_free_busy(calendar, window_start, window_end, tz))
    except Exception:  # noqa: BLE001
        result.skipped += 1
    seen: set[str] = set()
    unique = []
    for fact in sorted(result.facts, key=lambda f: (f.start, f.key)):
        if fact.key in seen:
            continue  # a feed that repeats an occurrence is counted once
        seen.add(fact.key)
        unique.append(fact)
    if len(unique) > max_events:
        result.truncated = True
        unique = unique[:max_events]
    result.facts = unique
    return result
