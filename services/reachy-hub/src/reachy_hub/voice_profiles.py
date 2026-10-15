"""Encrypted voice-profile storage (Phase 32A.V, ADR 0041; migration 038).

A profile is the owner's mean speaker embedding (a template, not audio). It is stored only as
AES-GCM ciphertext under a key held outside the database (`keyring.py`, SECRET_KEY_FILE). The
authenticated data binds the ciphertext to its profile id, owner and model version, so a row
copied onto another owner or relabelled with a different model version fails to decrypt instead
of being trusted. Nothing here logs or returns a template; the only way out is `load_template`,
which the verification service calls in-process.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from reachy_hub.keyring import Keyring, KeyringUnavailable
from shared.database import close_pool, open_pool
from shared.models.voice_identity import ClientKind, ClientProvenance, ProfileInfo

PROFILE_LABEL = "Owner"


@dataclass(frozen=True)
class StoredProfile:
    """The sealed row. `ciphertext` is useless without the keyring."""

    profile_id: str
    owner_id: str
    label: str
    version: int
    model_version: str
    sample_count: int
    enrolled_by: ClientProvenance
    key_id: str
    nonce: bytes
    ciphertext: bytes
    consented_at: datetime
    created_at: datetime

    def info(self) -> ProfileInfo:
        return ProfileInfo(
            profile_id=self.profile_id, label=self.label, version=self.version, model_version=self.model_version,
            sample_count=self.sample_count, created_at=self.created_at, enrolled_by=self.enrolled_by,
        )


def _aad(profile_id: str, owner_id: str, model_version: str) -> bytes:
    return f"voice-profile|{profile_id}|{owner_id}|{model_version}".encode()


def seal(keyring: Keyring, *, owner_id: str, model_version: str, template: list[float], sample_count: int,
         enrolled_by: ClientProvenance, consented_at: datetime, label: str = PROFILE_LABEL) -> StoredProfile:
    profile_id = uuid.uuid4().hex
    record = keyring.encrypt(_aad(profile_id, owner_id, model_version), json.dumps({"template": template}).encode())
    return StoredProfile(
        profile_id=profile_id, owner_id=owner_id, label=label, version=1, model_version=model_version,
        sample_count=sample_count, enrolled_by=enrolled_by, key_id=record["key_id"], nonce=record["nonce"],
        ciphertext=record["ciphertext"], consented_at=consented_at, created_at=datetime.now(UTC),
    )


def load_template(keyring: Keyring, profile: StoredProfile) -> list[float]:
    """Raises KeyringUnavailable when the key is missing or the row was altered or moved."""
    plain = keyring.decrypt(
        _aad(profile.profile_id, profile.owner_id, profile.model_version),
        {"key_id": profile.key_id, "nonce": profile.nonce, "ciphertext": profile.ciphertext},
    )
    try:
        return [float(x) for x in json.loads(plain)["template"]]
    except (ValueError, KeyError, TypeError):
        raise KeyringUnavailable() from None


class VoiceProfileStore(Protocol):
    async def get(self, owner_id: str) -> StoredProfile | None: ...
    async def put(self, profile: StoredProfile) -> StoredProfile:
        """Insert, or replace the owner's existing profile in place (version + 1). Returns the stored row."""
        ...
    async def delete(self, owner_id: str) -> bool: ...


class InMemoryVoiceProfileStore:
    def __init__(self) -> None:
        self._rows: dict[str, StoredProfile] = {}

    async def get(self, owner_id: str) -> StoredProfile | None:
        return self._rows.get(owner_id)

    async def put(self, profile: StoredProfile) -> StoredProfile:
        previous = self._rows.get(profile.owner_id)
        stored = StoredProfile(**{**profile.__dict__, "version": previous.version + 1 if previous else 1})
        self._rows[profile.owner_id] = stored
        return stored

    async def delete(self, owner_id: str) -> bool:
        return self._rows.pop(owner_id, None) is not None


_COLUMNS = ("profile_id, owner_id, label, version, model_version, sample_count, client_kind, client_id, device_id, "
            "key_id, nonce, ciphertext, consented_at, created_at")


def _from_row(row: tuple) -> StoredProfile:
    return StoredProfile(
        profile_id=row[0], owner_id=row[1], label=row[2], version=row[3], model_version=row[4], sample_count=row[5],
        enrolled_by=ClientProvenance(client_kind=ClientKind(row[6]), client_id=row[7], device_id=row[8]),
        key_id=row[9], nonce=bytes(row[10]), ciphertext=bytes(row[11]), consented_at=row[12], created_at=row[13],
    )


class PostgresVoiceProfileStore:
    def __init__(self, pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, source) -> PostgresVoiceProfileStore:
        return cls(await open_pool(source))

    async def close(self) -> None:
        await close_pool(self._pool)

    async def get(self, owner_id: str) -> StoredProfile | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM voice_profiles WHERE owner_id = %s AND kind = 'owner'", (owner_id,))
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def put(self, profile: StoredProfile) -> StoredProfile:
        # One statement: the unique partial index makes a concurrent re-enrolment replace, not duplicate.
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"""INSERT INTO voice_profiles ({_COLUMNS}) VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (owner_id) WHERE kind = 'owner' DO UPDATE SET
                    profile_id = EXCLUDED.profile_id, label = EXCLUDED.label, version = voice_profiles.version + 1,
                    model_version = EXCLUDED.model_version, sample_count = EXCLUDED.sample_count,
                    client_kind = EXCLUDED.client_kind, client_id = EXCLUDED.client_id, device_id = EXCLUDED.device_id,
                    key_id = EXCLUDED.key_id, nonce = EXCLUDED.nonce, ciphertext = EXCLUDED.ciphertext,
                    consented_at = EXCLUDED.consented_at, created_at = EXCLUDED.created_at
                RETURNING {_COLUMNS}""",
                (profile.profile_id, profile.owner_id, profile.label, profile.model_version, profile.sample_count,
                 profile.enrolled_by.client_kind.value, profile.enrolled_by.client_id, profile.enrolled_by.device_id,
                 profile.key_id, profile.nonce, profile.ciphertext, profile.consented_at, profile.created_at),
            )
            return _from_row(await cur.fetchone())

    async def delete(self, owner_id: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute("DELETE FROM voice_profiles WHERE owner_id = %s AND kind = 'owner'", (owner_id,))
            return cur.rowcount > 0
