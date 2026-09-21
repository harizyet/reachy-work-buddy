"""Robot registry: which reachy-embodiment instances exist and how to reach
them. Owned by reachy-hub per ADR 0001 ("auth / robot registry").

`RobotRegistry` is a Protocol so tests can use `InMemoryRobotRegistry`
without a real Postgres instance; production wires up
`PostgresRobotRegistry` (see postgres_registry.py).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class Robot(BaseModel):
    robot_id: str
    base_url: str


class RobotRegistry(Protocol):
    async def register(self, robot: Robot) -> None: ...
    async def get(self, robot_id: str) -> Robot | None: ...
    async def list(self) -> list[Robot]: ...


class InMemoryRobotRegistry:
    def __init__(self) -> None:
        self._robots: dict[str, Robot] = {}

    async def register(self, robot: Robot) -> None:
        self._robots[robot.robot_id] = robot

    async def get(self, robot_id: str) -> Robot | None:
        return self._robots.get(robot_id)

    async def list(self) -> list[Robot]:
        return list(self._robots.values())
