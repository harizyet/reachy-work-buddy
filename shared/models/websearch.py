"""Owner-configurable web-search grounding for the generic-conversation LLM
branch (Phase 24a). Same shape/precedent as shared/models/llm.py's
ProviderConfig plus Phase 21's routing mode; policy replaces routing mode.
The provider API key is a credential, never configuration — this model
never stores a plaintext key at rest, only the `secret_ref` a SecretStore
issues (see companion_core/websearch/postgres_store.py)."""

from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SearchPolicy(StrEnum):
    OFF = "off"
    AUTO = "auto"
    ALWAYS = "always"


class SearchProviderKind(StrEnum):
    # The bundled, self-hosted SearXNG container the deployment already
    # brings up (deploy/homelab/docker-compose.yml) — Companion Core knows
    # its internal address itself, so this needs no base_url/api_key from
    # the operator at all (Phase 24 cleanup: zero-configuration default).
    BUILTIN_SEARXNG = "builtin_searxng"
    # A separately-run/custom SearXNG instance — advanced users only.
    SEARXNG = "searxng"
    # Brave's hosted Search API (Phase 24d): fixed endpoint, needs only the
    # owner's subscription key. Added after scraping-based SearXNG engines
    # were CAPTCHA'd/suspended from the homelab's address during live use.
    BRAVE = "brave"


def _validate_url(value: str | None) -> str | None:
    if value is None:
        return value
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


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: SearchPolicy = SearchPolicy.OFF
    provider: SearchProviderKind = SearchProviderKind.BUILTIN_SEARXNG
    # Required for SEARXNG (an operator-supplied external endpoint), unset
    # and unused for BUILTIN_SEARXNG and BRAVE (companion_core/websearch/
    # provider.py knows both of their addresses itself).
    base_url: str | None = Field(default=None, max_length=2048)
    # Resolved plaintext, populated only at call time from SecretStore; never
    # the persisted representation (see postgres_store.py's secret_ref column).
    api_key: str | None = Field(default=None, max_length=4096, repr=False)
    result_count: int = Field(default=5, ge=1, le=10)
    timeout_seconds: float = Field(default=5.0, gt=0, le=15)
    updated_at: datetime | None = None

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return _validate_url(value)

    @model_validator(mode="after")
    def validate_policy(self):
        if self.policy == SearchPolicy.OFF:
            return self
        if self.provider == SearchProviderKind.SEARXNG and not self.base_url:
            raise ValueError("A non-Off search policy requires a configured provider base URL")
        if self.provider == SearchProviderKind.BRAVE and not self.api_key:
            raise ValueError("A non-Off Brave search policy requires an API key")
        return self


class SearchConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: SearchPolicy | None = None
    provider: SearchProviderKind | None = None
    base_url: str | None = None
    api_key: str | None = Field(default=None, max_length=4096, repr=False)
    result_count: int | None = Field(default=None, ge=1, le=10)
    timeout_seconds: float | None = Field(default=None, gt=0, le=15)
