"""Fixed, validated schema for the natural-language command-suggestion
classifier (Phase 24b, docs/phase-24b.md). This is the output of a
non-authoritative QoL classification step — no code path may use a
`SuggestionResult` to invoke an action directly; only a structured
`Command` (companion_core/commands/parser.py) parsed from explicit
`/reachy <action>` text may do that. `intent`/`speech_act` are drawn from
these fixed enums rather than open strings the model invents, so a
response that doesn't validate against this shape is a classifier
failure, not "best-effort interpreted" (see companion_core/
command_suggestion.py's fail-closed handling)."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Intent(StrEnum):
    NONE = "none"
    ROBOT_STANDBY = "robot_standby"
    ROBOT_RESUME = "robot_resume"


class SpeechAct(StrEnum):
    REQUEST = "request"
    QUESTION = "question"
    NEGATION = "negation"
    HYPOTHETICAL = "hypothetical"
    STATEMENT = "statement"
    OTHER = "other"


class SuggestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    speech_act: SpeechAct
    confidence: float = Field(ge=0.0, le=1.0)
