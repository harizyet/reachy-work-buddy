"""Role-based runtime LLM configuration; only local routing is enabled in Phase 19."""

from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LLMRole(StrEnum):
    LOCAL = "local"
    CLOUD = "cloud"


class ProviderKind(StrEnum):
    OPENAI_COMPATIBLE = "openai-compatible"


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderKind = ProviderKind.OPENAI_COMPATIBLE
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=4096, repr=False)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "Use an HTTP(S) base URL without credentials, query, or fragment"
            )
        return value.rstrip("/")

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Model must not be blank")
        return value.strip()


class LLMRoutingMode(StrEnum):
    LOCAL_ONLY = "local_only"


class LLMRoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: LLMRoutingMode = LLMRoutingMode.LOCAL_ONLY


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local: ProviderConfig | None = None
    # Reserved shape, not an enabled cloud-routing implementation.
    cloud: None = None
    routing: LLMRoutingConfig = Field(default_factory=LLMRoutingConfig)
    updated_at: datetime | None = None


class ProviderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderKind = ProviderKind.OPENAI_COMPATIBLE
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, max_length=4096, repr=False)


class LLMConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local: ProviderPatch | None = None
    cloud: None = None
    routing: LLMRoutingConfig = Field(default_factory=LLMRoutingConfig)


class LLMUsageEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    role: LLMRole = LLMRole.LOCAL
    model: str
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    latency_ms: float = 0
    success: bool = False
    error_message: str | None = None
