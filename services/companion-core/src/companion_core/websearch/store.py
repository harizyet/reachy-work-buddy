from datetime import UTC, datetime
from typing import Protocol

from shared.models.websearch import (
    HostedSearchProvider,
    SearchConfig,
    SearchConfigPatch,
)


def merge_search_config(current: SearchConfig, patch: SearchConfigPatch) -> SearchConfig:
    data = current.model_dump()
    changes = patch.model_dump(exclude_unset=True)
    for kind, hosted_patch in (changes.pop("hosted", None) or {}).items():
        data["hosted"][kind].update(hosted_patch)
    data.update(changes)
    data["updated_at"] = datetime.now(UTC)
    return SearchConfig.model_validate(data)


def _mask(key: str | None) -> str | None:
    # Never reveal the entire value even when the credential is short.
    return "********" + (key[-4:] if len(key) > 4 else "") if key else key


def masked_search_config(config: SearchConfig) -> dict:
    data = config.model_dump(mode="json")
    data["api_key"] = _mask(data["api_key"])
    for hosted in data["hosted"].values():
        hosted["api_key"] = _mask(hosted["api_key"])
    return data


def usage_period(now: datetime) -> str:
    """Calendar month in UTC, the reset boundary Tavily and Exa use; Brave's
    billing cycle may differ, which the default cap's margin absorbs."""
    return now.astimezone(UTC).strftime("%Y-%m")


class SearchSettingsStore(Protocol):
    async def get(self) -> SearchConfig: ...
    async def set(self, patch: SearchConfigPatch) -> SearchConfig: ...
    async def usage(self, period: str) -> dict[HostedSearchProvider, int]: ...
    async def reserve(self, provider: HostedSearchProvider, period: str, limit: int) -> bool:
        """Atomically count one call against the period unless the limit is
        already reached; False means the provider must not be called."""
    async def exhaust(self, provider: HostedSearchProvider, period: str, limit: int) -> None:
        """Mark the period used up after the provider itself reported so."""


class InMemorySearchSettingsStore:
    def __init__(self):
        self._config = SearchConfig()
        self._usage: dict[tuple[HostedSearchProvider, str], int] = {}

    async def get(self) -> SearchConfig:
        return self._config.model_copy(deep=True)

    async def set(self, patch: SearchConfigPatch) -> SearchConfig:
        self._config = merge_search_config(self._config, patch)
        return await self.get()

    async def usage(self, period: str) -> dict[HostedSearchProvider, int]:
        return {kind: self._usage.get((kind, period), 0) for kind in HostedSearchProvider}

    async def reserve(self, provider: HostedSearchProvider, period: str, limit: int) -> bool:
        used = self._usage.get((provider, period), 0)
        if used >= limit:
            return False
        self._usage[(provider, period)] = used + 1
        return True

    async def exhaust(self, provider: HostedSearchProvider, period: str, limit: int) -> None:
        self._usage[(provider, period)] = max(limit, self._usage.get((provider, period), 0))
