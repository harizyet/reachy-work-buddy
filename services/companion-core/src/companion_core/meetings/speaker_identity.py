"""Phase 54: owner-confirmed speaker identities (ADR 0038).

Diarization says WHICH label spoke when; only the owner can say who a label is. The raw labels and spans are never
rewritten. A confirmation is keyed by the diarization label and is tied to a fingerprint of the diarization it was
made against, so a re-run that produces different spans cannot silently hand an old name to a new label.

Pure functions: the stores persist the result and the routes validate the request."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from companion_core.meetings.models import (
    Meeting,
    SpeakerIdentity,
    SpeakerIdentityState,
    SupersededIdentities,
)

MAX_NAME = 60


class IdentityError(ValueError):
    """A request the owner can fix: an unknown label, an over-long name, a status that needs a name."""


def labels(diarization: list[dict[str, Any]] | None) -> list[str]:
    """Distinct diarization labels in order of first appearance."""
    seen: dict[str, None] = {}
    for span in diarization or []:
        if span.get("speaker"):
            seen.setdefault(str(span["speaker"]), None)
    return list(seen)


def fingerprint(diarization: list[dict[str, Any]] | None) -> str | None:
    """Identifies one diarization result: every span, to a tenth of a second. A re-run that moves a span or renames a
    label changes it; None when there is no diarization."""
    if not diarization:
        return None
    rows = sorted((str(s.get("speaker")), round(float(s.get("start", 0)), 1), round(float(s.get("end", 0)), 1)) for s in diarization)
    return hashlib.sha256("\n".join(f"{a}|{b}|{c}" for a, b, c in rows).encode()).hexdigest()[:16]


def clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if len(name) > MAX_NAME:
        raise IdentityError(f"speaker names are limited to {MAX_NAME} characters")
    return name


def names_of(identities: dict[str, SpeakerIdentity]) -> dict[str, str]:
    return {label: i.name for label, i in identities.items() if i.status == "named" and i.name}


def current_state(meeting: Meeting) -> SpeakerIdentityState:
    """The state with names set before Phase 54 (which have no record) adopted as confirmed names of the current diarization."""
    state = meeting.speaker_identity
    fp = fingerprint(meeting.diarization_segments)
    identities = dict(state.identities)
    for label, name in meeting.speaker_names.items():
        identities.setdefault(label, SpeakerIdentity(status="named", name=name, confirmed_at=meeting.updated_at))
    return state.model_copy(update={"identities": identities, "fingerprint": state.fingerprint or fp})


def apply(meeting: Meeting, decisions: dict[str, dict[str, Any]], *, now: datetime | None = None) -> tuple[SpeakerIdentityState, dict[str, str]]:
    """Merge the owner's decisions into the meeting's identities. `decisions` maps a label to
    `{"status": "named"|"unknown"|"skipped"|"clear", "name"?, "contact_id"?}`; `clear` removes the confirmation.
    Returns the new state and the `speaker_names` overlay. Raises IdentityError and changes nothing on a bad request."""
    known = set(labels(meeting.diarization_segments))
    state = current_state(meeting)
    identities = dict(state.identities)
    at = now or datetime.now(UTC)
    for label, decision in decisions.items():
        if label not in known:
            raise IdentityError(f"unknown speaker '{label[:40]}'")
        status = decision.get("status")
        if status == "clear":
            identities.pop(label, None)
            continue
        if status not in ("named", "unknown", "skipped"):
            raise IdentityError("status must be named, unknown, skipped or clear")
        name = clean_name(decision.get("name") or "")
        if status == "named" and not name:
            raise IdentityError("a name is needed to confirm a speaker; use unknown or skipped otherwise")
        contact = (decision.get("contact_id") or "").strip() or None
        if contact and status != "named":
            raise IdentityError("a contact can only go with a name")
        identities[label] = SpeakerIdentity(status=status, name=name or None, contact_id=contact, confirmed_at=at)
    return state.model_copy(update={"identities": identities}), names_of(identities)


def supersede(meeting: Meeting, new_diarization: list[dict[str, Any]]) -> tuple[SpeakerIdentityState, dict[str, str]]:
    """A diarization result is being replaced. If it differs from the one the confirmations were made against, they move
    to `superseded` (readable, never applied) and the display names reset to the generic labels. If it is identical, nothing changes."""
    state = current_state(meeting)
    new_fp = fingerprint(new_diarization)
    if not state.identities or state.fingerprint in (None, new_fp):
        return state.model_copy(update={"fingerprint": new_fp}), dict(meeting.speaker_names)
    kept = SupersededIdentities(fingerprint=state.fingerprint, identities=state.identities)
    return SpeakerIdentityState(fingerprint=new_fp, identities={}, superseded=kept), {}


def needs_review(meeting: Meeting) -> bool:
    return bool(meeting.speaker_identity.superseded and meeting.speaker_identity.superseded.identities)
