from datetime import UTC, datetime
from typing import Protocol

from shared.models.llm import LLMConfig, LLMConfigPatch, LLMRole, LLMUsageEntry


def merge_config(current: LLMConfig, patch: LLMConfigPatch) -> LLMConfig:
    data = current.model_dump()
    changes = patch.model_dump(exclude_unset=True)
    for role in ("local", "cloud"):
        if role in changes:
            update = changes.pop(role)
            data[role] = None if update is None else {**(data[role] or {}), **update}
    # First cloud setup opts into fallback; explicit policy always wins.
    if current.cloud is None and data["cloud"] is not None and "routing" not in changes:
        data["routing"] = {
            "mode": "local_with_cloud_fallback" if data["local"] else "cloud_only"
        }
    if "routing" in changes:
        changes["routing"] = {**data["routing"], **changes["routing"]}
    data.update(changes)
    data["updated_at"] = datetime.now(UTC)
    return LLMConfig.model_validate(data)


def masked_config(config: LLMConfig) -> dict:
    data = config.model_dump(mode="json")
    for role in ("local", "cloud"):
        if data[role] and data[role]["api_key"]:
            key = data[role]["api_key"]
            # Never reveal the entire value even when the credential is short.
            data[role]["api_key"] = "********" + (key[-4:] if len(key) > 4 else "")
    return data


def summarize(entries: list[LLMUsageEntry]) -> dict:
    def totals(rows):
        return {
            "calls": len(rows),
            "errors": sum(not r.success for r in rows),
            "prompt_tokens": sum(r.prompt_tokens or 0 for r in rows),
            "completion_tokens": sum(r.completion_tokens or 0 for r in rows),
            "unreported_token_calls": sum(
                r.prompt_tokens is None or r.completion_tokens is None for r in rows
            ),
            "avg_latency_ms": sum(r.latency_ms for r in rows) / len(rows)
            if rows
            else 0,
        }

    escalations = [r for r in entries if r.escalation_reason is not None]
    latest = max(escalations, key=lambda r: r.at) if escalations else None
    return {
        "latest_escalation": {
            "at": latest.at.isoformat(),
            "reason": latest.escalation_reason,
        }
        if latest
        else None,
        "summary": totals(entries),
        "by_role": {
            role.value: totals([r for r in entries if r.role == role])
            for role in LLMRole
        },
    }


class LLMSettingsStore(Protocol):
    async def get(self) -> LLMConfig: ...
    async def set(self, patch: LLMConfigPatch) -> LLMConfig: ...


class LLMUsageStore(Protocol):
    async def append(self, entry: LLMUsageEntry) -> None: ...
    async def list_recent(self, limit: int) -> list[LLMUsageEntry]: ...
    async def summary(self, since: datetime) -> dict: ...


class InMemoryLLMSettingsStore:
    def __init__(self):
        self._config = LLMConfig()

    async def get(self) -> LLMConfig:
        return self._config.model_copy(deep=True)

    async def set(self, patch: LLMConfigPatch) -> LLMConfig:
        self._config = merge_config(self._config, patch)
        return await self.get()


class InMemoryLLMUsageStore:
    def __init__(self):
        self._entries: list[LLMUsageEntry] = []

    async def append(self, entry: LLMUsageEntry) -> None:
        self._entries.append(entry.model_copy(deep=True))

    async def list_recent(self, limit: int) -> list[LLMUsageEntry]:
        return sorted(self._entries, key=lambda r: r.at, reverse=True)[:limit]

    async def summary(self, since: datetime) -> dict:
        return summarize([r for r in self._entries if r.at >= since])
