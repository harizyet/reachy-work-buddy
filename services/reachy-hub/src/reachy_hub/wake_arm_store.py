"""Owner arm for spoken wake monitoring, one per robot (Phase 24g, ADR 0023
wake-started sessions). It stays until the owner disarms, across hub and
robot restarts, so it is persisted rather than held with the process-local
voice sessions. Each arm gets a fresh `arm_id`; a candidate captured under
an older arm is refused."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True)
class WakeArm:
    robot_id: str
    user_id: str
    arm_id: str
    armed_at: datetime


def new_arm(robot_id: str, user_id: str) -> WakeArm:
    return WakeArm(robot_id, user_id, secrets.token_urlsafe(12), datetime.now(UTC))


class WakeArmStore(Protocol):
    async def get(self, robot_id: str) -> WakeArm | None: ...
    async def list(self) -> list[WakeArm]: ...
    async def set(self, arm: WakeArm) -> None: ...
    async def delete(self, robot_id: str) -> None: ...


class InMemoryWakeArmStore:
    def __init__(self) -> None:
        self._arms: dict[str, WakeArm] = {}

    async def get(self, robot_id: str) -> WakeArm | None:
        return self._arms.get(robot_id)

    async def list(self) -> list[WakeArm]:
        return list(self._arms.values())

    async def set(self, arm: WakeArm) -> None:
        self._arms[arm.robot_id] = arm

    async def delete(self, robot_id: str) -> None:
        self._arms.pop(robot_id, None)
