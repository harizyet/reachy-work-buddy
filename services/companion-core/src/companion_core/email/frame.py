"""The fixed text around a meeting-minutes message: who Reachy is, the accuracy note, and the processing and delivery disclosures (ADR 0040).

This is the trusted rendering layer. The owner edits only the middle (`body`); everything here is produced from the `frame` stored in the draft's `source` when it was prepared, from records
(who the owner is, where processing ran, which mail service delivers), never from model output and never from the edited body. The frame is part of the package hash and the final text is
hashed too, so approval covers it, and the same function renders the review preview and the message that is sent."""

from __future__ import annotations

from companion_core.meetings.provenance import step_phrase

TEMPLATE = "1"
GMAIL_HOSTS = ("smtp.gmail.com", "smtp.googlemail.com")

LOCAL_ONLY = "This meeting was processed entirely on private infrastructure. No meeting content was sent to external AI services."
NEUTRAL = ("Reachy is a self-hosted assistant designed with privacy in mind. A verified record of where this meeting was processed is not available, "
           "so this message makes no claim about it.")


class FrameError(ValueError):
    pass


def delivery_for(host: str) -> str:
    """The mail service the message will really pass through, from the configured sender: 'gmail' or 'other'."""
    return "gmail" if (host or "").strip().lower() in GMAIL_HOSTS else "other"


def processing_statement(provenance: dict) -> str:
    """The sentence about AI processing, chosen only from the assessed provenance: nothing else decides it."""
    status = provenance.get("status")
    if status == "local":
        return LOCAL_ONLY
    if status == "external":
        steps = provenance.get("external_steps") or []
        text = f"Some meeting content was processed by an external AI service{(' for ' + step_phrase(steps)) if steps else ''}."
        return text + (" All other processing took place on private infrastructure." if provenance.get("rest_local") else "")
    return NEUTRAL


def delivery_statement(delivery: str, *, has_attachment: bool) -> str:
    what = "the email and its attachment are" if has_attachment else "the email is"
    if delivery == "gmail":
        return f"Email delivery is separate from AI processing: this message is delivered through Gmail, so {what} transmitted through Google's email service."
    return f"Email delivery is separate from AI processing: this message is delivered through an external email provider, so {what} transmitted through that provider's service."


def _possessive(name: str) -> str:
    return f"{name}'s"


def parts(frame: dict | None, *, has_attachment: bool) -> tuple[str, str]:
    """(before, after): the fixed text above and below the editable body."""
    if not frame or frame.get("template") != TEMPLATE:
        raise FrameError("this message has no verified disclosure text; prepare it again")
    owner = (frame.get("owner") or "").strip()
    if not owner:
        raise FrameError("the owner's name is not set")
    mine = _possessive(owner)
    head = [
        "Hi everyone,",
        "",
        f"I'm Reachy, {mine} personal AI assistant.",
        "",
        f"I'm sharing the summary and meeting minutes from our recent discussion on {mine} behalf.",
        "",
        (f"A little about me: I'm Reachy, a self-hosted AI assistant created by {owner} and designed with privacy in mind. My purpose is to help {owner} manage day-to-day work, "
         "from recording meetings and preparing summaries to organizing tasks and reminders. "
         f"I prioritize processing information locally on {mine} private infrastructure, minimizing the need to share sensitive information with any external services."),
        "",
        f"Meeting: {frame.get('title', '')}",
        f"Date: {frame.get('when', '')}",
    ]
    if frame.get("participants"):
        head.append("Participants: " + ", ".join(frame["participants"]))
    tail = []
    if has_attachment:
        tail += ["The detailed meeting minutes are attached for your reference.", ""]
    tail += [
        ("A note about accuracy: Although I aim to capture discussions accurately, I'm an AI assistant and can make mistakes, including misunderstanding statements or attributing "
         f"comments to the wrong speaker. Please let {owner} know if anything needs correcting."),
        "",
        "Best regards,",
        "Reachy",
        f"{mine} Personal AI Assistant",
        "",
        "--",
        f"{processing_statement(frame.get('provenance') or {})} {delivery_statement(frame.get('delivery', 'other'), has_attachment=has_attachment)} Reviewed and approved by {owner} before sending.",
    ]
    return "\n".join(head) + "\n\n", "\n\n" + "\n".join(tail) + "\n"


def render(body: str, frame: dict | None, *, has_attachment: bool) -> str:
    before, after = parts(frame, has_attachment=has_attachment)
    return before + body.strip("\n") + after
