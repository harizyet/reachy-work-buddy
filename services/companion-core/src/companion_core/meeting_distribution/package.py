"""Builds the content of a meeting-minutes email from what the owner has already approved or can see (Phase 55, ADR 0039). Pure functions; nothing here calls a model or sends anything.

Included: title, date and time zone, participant names, the stored summary and minutes (owner-corrected speaker names), decisions with their evidence and an honest confirmation label, and
**only owner-confirmed** action items. Never included: the recording, the raw transcript, rejected or pending findings, model prompts or internal analysis. Decisions are labelled
because Phase 31 never asks the owner to confirm them individually."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC
from zoneinfo import ZoneInfo

from companion_core.meeting_distribution import pdf as pdf_writer
from companion_core.meetings.models import Meeting, speaker_basis

SUMMARY_CHARS = 1400  # the email body's summary; the whole summary and the minutes are in the PDF
DECISION_LABEL = "Recorded from the meeting transcript by an automatic analysis; not individually confirmed."
ACTION_LABEL = "Confirmed by the owner."


@dataclass
class Package:
    subject: str
    body: str
    pdf: bytes | None
    pdf_name: str
    pdf_error: str | None
    source: dict
    warnings: list[str] = field(default_factory=list)
    counts: dict = field(default_factory=dict)


def _when(meeting: Meeting, timezone: str) -> str:
    moment = meeting.started_at or meeting.created_at
    try:
        zone = ZoneInfo(timezone)
    except Exception:  # noqa: BLE001 - an unknown zone name falls back to UTC rather than failing the draft
        zone, timezone = UTC, "UTC"
    local = moment.astimezone(zone)
    return f"{local.strftime('%a %d %b %Y, %H:%M')} ({timezone})"


def _stamp(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def _participants(meeting: Meeting) -> list[str]:
    named = [n for n in meeting.speaker_names.values() if n]
    return list(dict.fromkeys([*meeting.participants, *named]))


def _lead(text: str, limit: int) -> tuple[str, bool]:
    """Whole paragraphs up to `limit` characters (at least the first one, cut at a sentence if it alone is longer). True when something was left out."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    out, size = [], 0
    for paragraph in paragraphs:
        if out and size + len(paragraph) > limit:
            return "\n\n".join(out), True
        out.append(paragraph)
        size += len(paragraph)
    joined = "\n\n".join(out)
    if len(joined) > limit * 2:
        cut = joined[: limit * 2]
        return cut[: max(cut.rfind(". "), cut.rfind("\n")) + 1 or len(cut)].strip(), True
    return joined, False


def _filename(title: str, meeting: Meeting) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")[:50] or "meeting"
    return f"{stem}-minutes-{(meeting.started_at or meeting.created_at).strftime('%Y-%m-%d')}.pdf"


def build(meeting: Meeting, analysis: dict | None, *, timezone: str, include_pdf: bool, sensitive_acknowledged: bool = False) -> Package:
    """`analysis` is the Phase 31 status view (or None when the feature is off or nothing was analysed)."""
    warnings: list[str] = []
    when = _when(meeting, timezone)
    people = _participants(meeting)
    summary = meeting.summary.text.strip() if meeting.summary else ""
    minutes = meeting.minutes.text.strip() if meeting.minutes else ""

    decisions: list[dict] = []
    actions: list[dict] = []
    pending = skipped = 0
    state_note = None
    if analysis and analysis.get("run"):
        if analysis.get("transcript_changed_since_run"):
            state_note = "The meeting analysis is out of date (the transcript or a speaker name changed since it ran), so no decisions or actions are included. Run the analysis again to include them."
        else:
            for item in analysis.get("items", []):
                if item.get("source_changed") or item.get("attribution_changed"):
                    skipped += 1
                    continue
                if item["kind"] == "decision" and item["status"] == "noted" and item.get("evidence"):
                    decisions.append(item)
                elif item["kind"] == "action":
                    if item["status"] == "accepted":
                        actions.append(item)
                    elif item["status"] == "pending":
                        pending += 1
    elif analysis is None:
        state_note = None
    if state_note:
        warnings.append(state_note)
    if skipped:
        warnings.append(f"{skipped} finding{'s' if skipped != 1 else ''} left out because the transcript changed since the analysis.")
    if pending:
        warnings.append(f"{pending} action candidate{'s' if pending != 1 else ''} not included: you have not confirmed {'them' if pending != 1 else 'it'}.")

    title = meeting.title.strip() or "Meeting"
    subject = f"Meeting minutes: {title}"[:180]
    head = [f"Summary and minutes of “{title}”", f"Date: {when}"]
    pdf_blocks: list[tuple[str, str]] = [("title", title), ("p", f"Date: {when}")]
    if people:
        head.append("Participants: " + ", ".join(people))
        pdf_blocks.append(("p", "Participants: " + ", ".join(people)))
    head.append("")
    pdf_blocks.append(("gap", ""))
    if summary:
        pdf_blocks += [("h", "Summary"), ("p", summary), ("gap", "")]
    if minutes:
        pdf_blocks += [("h", "Minutes"), ("p", minutes), ("gap", "")]
    findings: list[str] = []
    if decisions:
        findings += ["DECISIONS", f"({DECISION_LABEL})"]
        pdf_blocks += [("h", "Decisions"), ("p", DECISION_LABEL)]
        for item in decisions:
            ev = item["evidence"][0]
            line = f"{item['text']}  [{_stamp(ev['start'])}" + (f", {ev['speaker']}" if ev.get("speaker") else "") + "]"
            findings += [f"- {line}", f"    “{ev['quote']}”"]
            pdf_blocks += [("li", line), ("quote", f"“{ev['quote']}”")]
        findings.append("")
        pdf_blocks.append(("gap", ""))
    if actions:
        findings += ["ACTION ITEMS", f"({ACTION_LABEL})"]
        pdf_blocks += [("h", "Action items"), ("p", ACTION_LABEL)]
        for item in actions:
            text = item.get("task_text") or item["text"]
            findings.append(f"- {text}")
            pdf_blocks.append(("li", text))
        findings.append("")

    pdf_bytes, pdf_error = None, None
    if include_pdf and (minutes or summary):
        try:
            pdf_bytes = pdf_writer.render(f"{title} - minutes", pdf_blocks)
        except pdf_writer.PdfError as exc:
            pdf_error = str(exc)
            warnings.append(f"The PDF could not be made: {exc}")
    attach = pdf_bytes is not None  # the text of the message follows what is really attached: if there is no PDF, the minutes are in the body

    lines = list(head)
    if summary:
        lead, cut = _lead(summary, SUMMARY_CHARS) if attach else (summary, False)
        lines += ["SUMMARY", lead] + (["(The complete summary is in the attached PDF.)"] if cut else []) + [""]
    if minutes and not attach:
        lines += ["MINUTES", minutes, ""]
    lines += findings
    if attach:
        lines += ["The full minutes are attached as a PDF.", ""]
    lines += ["Sent with Reachy on the owner's behalf, after the owner reviewed and approved this message."]
    source = {
        "meeting_id": meeting.id, "summary_at": meeting.summary.generated_at.isoformat() if meeting.summary else None,
        "minutes_at": meeting.minutes.generated_at.isoformat() if meeting.minutes else None, "speaker_basis": speaker_basis(meeting.speaker_names) if meeting.speaker_names else None,
        "analysis_run": (analysis or {}).get("run", {}).get("id") if analysis and analysis.get("run") else None,
        "decisions": sorted(i["id"] for i in decisions), "actions": sorted(i["id"] for i in actions),
        "sensitivity": meeting.sensitivity.value, "sensitive_acknowledged": sensitive_acknowledged,
    }
    return Package(subject=subject, body="\n".join(lines).strip() + "\n", pdf=pdf_bytes, pdf_name=_filename(title, meeting), pdf_error=pdf_error, source=source, warnings=warnings,
                   counts={"decisions": len(decisions), "actions": len(actions), "pending_actions": pending, "participants": len(people)})


def source_is_current(source: dict, meeting: Meeting) -> bool:
    """Has what the package was prepared from changed? (a regenerated summary or minutes, or renamed speakers). The approved text itself never changes; this only blocks queueing stale content."""
    return (
        source.get("summary_at") == (meeting.summary.generated_at.isoformat() if meeting.summary else None)
        and source.get("minutes_at") == (meeting.minutes.generated_at.isoformat() if meeting.minutes else None)
        and source.get("speaker_basis") == (speaker_basis(meeting.speaker_names) if meeting.speaker_names else None)
    )
