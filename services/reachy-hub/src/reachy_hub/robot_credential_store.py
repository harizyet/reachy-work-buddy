"""Per-robot credential verification for the ADR 0019 WSS control
connection.

Phase 22's first slice: in-memory only, loaded from an env var at
startup. Deliberately not Postgres-backed yet — ADR 0019 explicitly
allows this ("This need not wait for Phase 23's core-owned provider
SecretStore... initial robot provisioning can use restricted
configuration files"), and adding one more ad hoc startup-DDL table
right before Phase 23 introduces real schema migrations would just be
more of the thing that prerequisite exists to clean up. Real limitation
of this slice, not hidden: a hub restart requires re-provisioning via
the same env var/file, same as before restart — there is no persistence
across restarts here.

Reuses user_store.py's PBKDF2 hash/verify so the hub never needs to
retain a robot's plaintext token past provisioning — ADR 0019: "the hub
can retain token verifiers rather than plaintext tokens."
"""

from __future__ import annotations

import json
import os
from typing import Protocol

from reachy_hub.user_store import hash_password, verify_password


class RobotCredentialStore(Protocol):
    async def verify(self, robot_id: str, token: str) -> bool: ...


class InMemoryRobotCredentialStore:
    def __init__(self, hashed_tokens: dict[str, str] | None = None) -> None:
        self._hashed_tokens: dict[str, str] = dict(hashed_tokens or {})

    def provision(self, robot_id: str, token: str) -> None:
        self._hashed_tokens[robot_id] = hash_password(token)

    def revoke(self, robot_id: str) -> None:
        self._hashed_tokens.pop(robot_id, None)

    async def verify(self, robot_id: str, token: str) -> bool:
        encoded = self._hashed_tokens.get(robot_id)
        if encoded is None:
            return False
        return verify_password(token, encoded)


def load_from_env(env_var: str = "ROBOT_TOKENS") -> InMemoryRobotCredentialStore:
    """Parses `ROBOT_TOKENS` as a JSON object: `{"<robot_id>": "<token>"}`.

    Hashes each token immediately; the plaintext values read from the
    environment are not retained past this function returning. A
    missing/unset/empty env var yields an empty store — no robot can
    authenticate, i.e. this fails closed, matching every other optional
    integration's "absent means gated off, never silently open" pattern
    in this repo (see reachy-hub/app.py's REMOTE_UI_TOKEN handling).
    """
    raw = os.environ.get(env_var)
    store = InMemoryRobotCredentialStore()
    if not raw:
        return store
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{env_var} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        # ValueError, not TypeError, to match every other "this config
        # value is malformed" error in this function (the JSON decode
        # error above, the per-token check below) -- callers should only
        # need to catch one exception type for "ROBOT_TOKENS is invalid".
        raise ValueError(f"{env_var} must be a JSON object of {{robot_id: token}}")  # noqa: TRY004
    for robot_id, token in parsed.items():
        if not isinstance(token, str) or not token:
            raise ValueError(f"{env_var}[{robot_id!r}] must be a non-empty string token")
        store.provision(robot_id, token)
    return store
