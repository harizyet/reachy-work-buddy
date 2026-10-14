"""Where a meeting's content was processed, recorded as it happens and judged here (ADR 0040).

Every step that reads the recording or its transcript leaves an append-only `ProcessingEvent`: the step, where it ran (`local`, `external` or `unverified`) and, for generated outputs, which output it
produced. `assess` turns those records into one verdict for a message about the meeting. It never asks a model and never assumes: a claim of private processing needs positive local evidence for
every step the message depends on, any external processing is reported as such, and missing or unclassifiable evidence gives the neutral verdict.

Events are never rewritten. A summary regenerated locally after a cloud attempt still leaves the cloud event, because the content was sent."""

from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

Location = Literal["local", "external", "unverified"]

# The pipeline steps, in the order a meeting passes through them, and the words a reader of the email sees for each.
STEP_LABELS: dict[str, str] = {
    "transcription": "transcription",
    "diarization": "speaker detection",
    "speaker_processing": "speaker processing",
    "title": "the meeting title",
    "summary": "the summary",
    "minutes": "the minutes",
    "analysis": "the decisions and action items",
    "corrections": "transcript correction suggestions",
    "conversation": "a question about the meeting",
}
# Without an event for each of these the message cannot claim private processing.
PIPELINE_STEPS = ("transcription", "diarization", "speaker_processing")

# Host names that are on the private network by construction: a single-label name is a Compose service or an internal DNS short name.
_PRIVATE_SUFFIXES = (".local", ".lan", ".internal", ".home.arpa", ".localdomain")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")  # carrier-grade NAT space, used by Tailscale


class ProcessingEvent(BaseModel):
    step: str
    location: Location
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # What the event produced, so a later check can tie it to the output being sent: the generated_at of a summary or minutes, the id of an analysis run.
    subject: str | None = Field(default=None, max_length=200)


def endpoint_location(url: str | None) -> Location:
    """Where an HTTP endpoint is: `local` for a loopback, private-network, link-local or Tailscale address or an internal-looking name, otherwise `unverified`. A public host name is never called
    local, because a name alone cannot show that the machine behind it is private."""
    if not url:
        return "unverified"
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return "unverified"
    if not host:
        return "unverified"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host == "localhost" or host == "host.docker.internal" or "." not in host or host.endswith(_PRIVATE_SUFFIXES):
            return "local"
        return "unverified"
    if address.is_loopback or address.is_private or address.is_link_local or (address.version == 4 and address in _CGNAT):
        return "local"
    return "unverified"


def event(step: str, location: Location, *, subject: str | None = None) -> ProcessingEvent:
    return ProcessingEvent(step=step, location=location, subject=subject)


@dataclass
class Provenance:
    status: Literal["local", "external", "unverified"]
    external_steps: list[str] = field(default_factory=list)
    rest_local: bool = False  # for an external verdict: every other step is positively recorded as local
    reasons: list[str] = field(default_factory=list)  # for the owner's review only; never put in a message

    @property
    def digest(self) -> str:
        """What a prepared message depends on in this verdict. If it differs later, the message was written about different processing."""
        text = f"{self.status}|{','.join(sorted(self.external_steps))}|{int(self.rest_local)}"
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def as_dict(self) -> dict:
        return {"status": self.status, "external_steps": sorted(self.external_steps), "rest_local": self.rest_local, "digest": self.digest}


def assess(meeting, *, analysis_run: str | None = None) -> Provenance:
    """The verdict for a message made from `meeting` now. `analysis_run` is the id of the analysis whose findings the message includes, if any.

    external:    at least one recorded step ran on an external AI service (whatever else is missing).
    unverified:  no external step is recorded, but some needed step has no local record or an unclassifiable one.
    local:       every needed step is positively recorded as local and nothing is recorded elsewhere."""
    events: list[ProcessingEvent] = list(getattr(meeting, "processing_events", None) or [])
    external = sorted({e.step for e in events if e.location == "external"}, key=_order)
    reasons: list[str] = []

    def local_for(step: str, subject: str | None = None) -> bool:
        return any(e.step == step and e.location == "local" and (subject is None or e.subject == subject) for e in events)

    for step in PIPELINE_STEPS:
        if not local_for(step):
            reasons.append(f"no record that {STEP_LABELS[step]} ran on private infrastructure")
    for kind in ("summary", "minutes"):
        output = getattr(meeting, kind, None)
        if output is not None and kind not in external and not local_for(kind, output.generated_at.isoformat()):
            reasons.append(f"no record that the current {kind} was written on private infrastructure")
    if getattr(meeting, "title_source", "default") == "generated" and "title" not in external and not local_for("title"):
        reasons.append("no record that the meeting title was written on private infrastructure")
    if analysis_run is not None and "analysis" not in external and not local_for("analysis", analysis_run):
        reasons.append("no record that the meeting analysis ran on private infrastructure")
    unclassified = sorted({e.step for e in events if e.location == "unverified"}, key=_order)
    reasons += [f"{STEP_LABELS.get(step, step)} ran somewhere that could not be confirmed as private" for step in unclassified]

    if external:
        return Provenance("external", external, rest_local=not reasons, reasons=reasons)
    return Provenance("unverified" if reasons else "local", [], reasons=reasons)


def _order(step: str) -> int:
    keys = list(STEP_LABELS)
    return keys.index(step) if step in keys else len(keys)


def step_phrase(steps: list[str]) -> str:
    """'the summary and the minutes', 'transcription, the summary and the minutes'."""
    names = [STEP_LABELS.get(s, s) for s in sorted(steps, key=_order)]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]
