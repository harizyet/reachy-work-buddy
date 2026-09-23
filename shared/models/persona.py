"""Assistant identity/system-prompt configuration, separate from LLM provider settings."""

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_NAME = "Reachy"
DEFAULT_SYSTEM_PROMPT = (
    "You are Reachy, an embodied work assistant. You help with tasks, "
    "calendar, email, reminders, and general questions. Keep replies "
    "concise and practical, and be clear when something is outside what "
    "you can do."
)


class PersonaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default=DEFAULT_NAME, min_length=1, max_length=64)
    system_prompt: str = Field(default=DEFAULT_SYSTEM_PROMPT, min_length=1, max_length=4000)


class PersonaPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=64)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=4000)
