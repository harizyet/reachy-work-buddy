from datetime import UTC, datetime
from typing import Protocol

from shared.models.websearch import SearchConfig, SearchConfigPatch


def merge_search_config(current: SearchConfig, patch: SearchConfigPatch) -> SearchConfig:
    data = current.model_dump()
    data.update(patch.model_dump(exclude_unset=True))
    data["updated_at"] = datetime.now(UTC)
    return SearchConfig.model_validate(data)


def masked_search_config(config: SearchConfig) -> dict:
    data = config.model_dump(mode="json")
    if data["api_key"]:
        key = data["api_key"]
        # Never reveal the entire value even when the credential is short.
        data["api_key"] = "********" + (key[-4:] if len(key) > 4 else "")
    return data


class SearchSettingsStore(Protocol):
    async def get(self) -> SearchConfig: ...
    async def set(self, patch: SearchConfigPatch) -> SearchConfig: ...


class InMemorySearchSettingsStore:
    def __init__(self):
        self._config = SearchConfig()

    async def get(self) -> SearchConfig:
        return self._config.model_copy(deep=True)

    async def set(self, patch: SearchConfigPatch) -> SearchConfig:
        self._config = merge_search_config(self._config, patch)
        return await self.get()
