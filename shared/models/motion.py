"""Robot-local conversational motion settings, owned by embodiment."""

from pydantic import BaseModel, ConfigDict


class MotionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    conversation_motion: bool
    speech_wobble: bool


class MotionSettingsStatus(MotionSettings):
    conversation_active: bool
