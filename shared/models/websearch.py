"""Owner-configurable web-search grounding for the generic-conversation LLM
branch (Phase 24a). Same shape/precedent as shared/models/llm.py's
ProviderConfig plus Phase 21's routing mode; policy replaces routing mode.
Provider API keys are credentials, never configuration — this model never
stores a plaintext key at rest, only the `secret_ref` a SecretStore issues
(see companion_core/websearch/postgres_store.py).

Phase 24a follow-up (found in 24d): searches rotate across the hosted providers the owner enabled
(Brave, Exa, Tavily), each capped at a monthly count kept under its free
tier, and fall back to SearXNG only after every hosted tier failed or hit
its cap (companion_core/websearch/rotation.py)."""

from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SearchPolicy(StrEnum):
    OFF = "off"
    AUTO = "auto"
    ALWAYS = "always"


class SearchFallbackKind(StrEnum):
    # The bundled, self-hosted SearXNG container the deployment already
    # brings up (deploy/homelab/docker-compose.yml) — Companion Core knows
    # its internal address itself, so this needs no base_url/api_key from
    # the operator at all (Phase 24 cleanup: zero-configuration default).
    BUILTIN_SEARXNG = "builtin_searxng"
    # A separately-run/custom SearXNG instance — advanced users only.
    SEARXNG = "searxng"
    NONE = "none"


class HostedSearchProvider(StrEnum):
    # Hosted APIs with fixed endpoints that need only the owner's key. Added
    # after scraping-based SearXNG engines were CAPTCHA'd/suspended from the
    # homelab's address during live use. Declaration order breaks rotation
    # ties.
    BRAVE = "brave"
    EXA = "exa"
    TAVILY = "tavily"


# Kept below each free allowance as of 2026-09 (Brave: $5/month credit ≈
# 1,000 queries, after which the card on file is billed; Exa: $10/month
# credit ≈ 1,250 searches with highlights; Tavily: 1,000 basic-search
# credits/month). The count is Reachy's own, so the margin also absorbs
# calls made with the same key elsewhere and provider cycles that don't
# start on the 1st.
DEFAULT_MONTHLY_LIMITS = {
    HostedSearchProvider.BRAVE: 900,
    HostedSearchProvider.EXA: 900,
    HostedSearchProvider.TAVILY: 900,
}


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


class HostedProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    # Resolved plaintext, populated only at call time from SecretStore.
    api_key: str | None = Field(default=None, max_length=4096, repr=False)
    monthly_limit: int = Field(ge=1, le=1_000_000)


def _default_hosted() -> dict[HostedSearchProvider, HostedProviderConfig]:
    return {
        kind: HostedProviderConfig(monthly_limit=limit)
        for kind, limit in DEFAULT_MONTHLY_LIMITS.items()
    }


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: SearchPolicy = SearchPolicy.OFF
    hosted: dict[HostedSearchProvider, HostedProviderConfig] = Field(default_factory=_default_hosted)
    fallback: SearchFallbackKind = SearchFallbackKind.BUILTIN_SEARXNG
    # base_url/api_key belong to the External SearXNG fallback only; the
    # built-in container's address is known to companion_core/websearch/
    # provider.py.
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

    @field_validator("hosted")
    @classmethod
    def fill_hosted(cls, value):
        return {**_default_hosted(), **value}

    @model_validator(mode="after")
    def validate_policy(self):
        if self.policy == SearchPolicy.OFF:
            return self
        if self.fallback == SearchFallbackKind.SEARXNG and not self.base_url:
            raise ValueError("A non-Off search policy requires a configured provider base URL")
        for kind, hosted in self.hosted.items():
            if hosted.enabled and not hosted.api_key:
                raise ValueError(f"A non-Off search policy requires an API key for enabled {kind.value}")
        if self.fallback == SearchFallbackKind.NONE and not any(h.enabled for h in self.hosted.values()):
            raise ValueError("A non-Off search policy requires a hosted provider or a SearXNG fallback")
        return self


class HostedProviderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    # Unset keeps the saved key; explicit null removes it.
    api_key: str | None = Field(default=None, max_length=4096, repr=False)
    monthly_limit: int | None = Field(default=None, ge=1, le=1_000_000)


class SearchConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: SearchPolicy | None = None
    hosted: dict[HostedSearchProvider, HostedProviderPatch] | None = None
    fallback: SearchFallbackKind | None = None
    base_url: str | None = None
    api_key: str | None = Field(default=None, max_length=4096, repr=False)
    result_count: int | None = Field(default=None, ge=1, le=10)
    timeout_seconds: float | None = Field(default=None, gt=0, le=15)


class SearchSource(BaseModel):
    """A normalized result returned for one conversation turn."""

    title: str
    url: str
    snippet: str
    source_domain: str


class TurnWebSearch(BaseModel):
    """Core-authored search evidence; absent when the turn did not search."""

    query: str
    failed: bool = False
    results: list[SearchSource] = Field(default_factory=list)
