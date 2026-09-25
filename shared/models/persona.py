"""Assistant identity/system-prompt configuration, separate from LLM provider settings.

Location and time zone (Phase 24a follow-up) give every conversation turn the owner's
local date/time and place, so relative dates and weather resolve correctly."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_NAME = "Reachy"
DEFAULT_SYSTEM_PROMPT = (
    "You are Reachy, an embodied work assistant. You help with tasks, "
    "calendar, email, reminders, and general questions. Keep replies "
    "concise and practical, and be clear when something is outside what "
    "you can do."
)


DEFAULT_TIMEZONE = "UTC"


def _validate_timezone(value: str | None) -> str | None:
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Use an IANA time zone such as Asia/Singapore") from None
    return value


def _blank_to_none(value: str | None) -> str | None:
    return value.strip() or None if isinstance(value, str) else value


class PersonaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default=DEFAULT_NAME, min_length=1, max_length=64)
    system_prompt: str = Field(default=DEFAULT_SYSTEM_PROMPT, min_length=1, max_length=4000)
    # Free text such as "Singapore" or "Kuala Lumpur, Malaysia"; unset adds
    # no location to the model context or to weather searches.
    location: str | None = Field(default=None, max_length=120)
    timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=64)

    _location = field_validator("location", mode="before")(_blank_to_none)
    _timezone = field_validator("timezone")(_validate_timezone)


class PersonaPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=64)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    location: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)

    _location = field_validator("location", mode="before")(_blank_to_none)
    _timezone = field_validator("timezone")(_validate_timezone)
