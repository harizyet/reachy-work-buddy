"""Robot backend abstraction.

Phase 2 only needs the semantic HTTP layer to prove it can drive *something*
named after a behaviour; it does not need real Reachy hardware. This mirrors
Jarvis's own RobotController, which exposes a `sim` property precisely so the
rest of the stack doesn't care whether hardware is attached (see
docs/jarvis-baseline.md, robot/controller.py section).

A real Reachy-backed implementation (wrapping the `reachy_mini` SDK the way
Jarvis's RobotController does) is added when hardware is available to test
against; it plugs in behind the same RobotBackend protocol so nothing above
this module changes.
"""

from __future__ import annotations

import logging
from typing import Protocol

from shared.models.embodiment import Behaviour

log = logging.getLogger(__name__)


class RobotBackend(Protocol):
    @property
    def connected(self) -> bool: ...

    @property
    def sim(self) -> bool: ...

    def play_behaviour(self, name: Behaviour, parameters: dict[str, str]) -> None: ...


class SimulatedRobotBackend:
    """Logs behaviour triggers instead of driving hardware."""

    def __init__(self) -> None:
        self._connected = True

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def sim(self) -> bool:
        return True

    def play_behaviour(self, name: Behaviour, parameters: dict[str, str]) -> None:
        log.info("sim: playing behaviour %s params=%s", name.value, parameters)
