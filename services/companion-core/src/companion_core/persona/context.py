"""Owner-local date, time and location for generic conversation turns
(Phase 24d). Without it the model answered relative-date questions from its
training cutoff ("close to 9 months" for a 16-month term)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from shared.models.persona import PersonaConfig


def context_message(persona: PersonaConfig, now: datetime) -> dict[str, str]:
    local = now.astimezone(ZoneInfo(persona.timezone))
    offset = local.strftime("%z")
    when = (
        f"{local.strftime('%A')} {local.day} {local.strftime('%B %Y, %H:%M')} "
        f"({persona.timezone}, UTC{offset[:3]}:{offset[3:]})"
    )
    parts = [f"Current local date and time: {when}."]
    if persona.location:
        parts.append(
            f"The owner is in {persona.location}; use it as the default place "
            "for location-dependent questions such as weather."
        )
    parts.append("Use this for relative dates such as today, tomorrow or how long ago.")
    return {"role": "system", "content": " ".join(parts)}
