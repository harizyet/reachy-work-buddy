from typing import Protocol

from shared.models.persona import PersonaConfig, PersonaPatch


def merge_persona(current: PersonaConfig, patch: PersonaPatch) -> PersonaConfig:
    data = current.model_dump()
    data.update(patch.model_dump(exclude_unset=True))
    return PersonaConfig.model_validate(data)


class PersonaStore(Protocol):
    async def get(self) -> PersonaConfig: ...
    async def set(self, patch: PersonaPatch) -> PersonaConfig: ...


class InMemoryPersonaStore:
    def __init__(self):
        self._config = PersonaConfig()

    async def get(self) -> PersonaConfig:
        return self._config.model_copy(deep=True)

    async def set(self, patch: PersonaPatch) -> PersonaConfig:
        self._config = merge_persona(self._config, patch)
        return await self.get()
