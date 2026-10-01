"""29.19: provider credentials (e.g. a Claude Code API key), encrypted at
rest, never returned over HTTP once set. This service keeps its own key
material rather than importing companion_core.secrets.Keyring — ADR 0001
forbids sibling-service runtime imports, and 29.19 explicitly calls for
agent credentials to be separate from Reachy's own SecretStore, not a
reuse of it. Single active key, no rotation — unlike companion-core's
multi-key Keyring, this service has no deployed credentials yet to migrate,
so rotation support is deferred until it does.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from shared.models.coding_agent import CredentialKind, ProviderCredentialRecord


class CredentialUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Credential key unavailable; check CODING_AGENT_SECRET_KEY_FILE")


@dataclass(frozen=True)
class CredentialKeyring:
    key: bytes

    @classmethod
    def from_file(cls, path: str | None = None) -> CredentialKeyring:
        try:
            target = Path(path or os.environ["CODING_AGENT_SECRET_KEY_FILE"])
            with target.open("rb") as stream:
                info = os.fstat(stream.fileno())
                # Same check as companion_core.secrets.Keyring: reject a
                # key file that is not a regular file or is group/world
                # readable (0o077 catches any bit outside owner).
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                    raise ValueError("permissions")
                data = json.load(stream)
            key = base64.b64decode(data["key"], validate=True)
            if len(key) != 32:
                raise ValueError("key length")
            return cls(key)
        except (OSError, KeyError, ValueError, TypeError):
            raise CredentialUnavailable() from None

    def encrypt(self, provider: str, value: str) -> dict:
        nonce = os.urandom(12)
        # provider as AAD: a ciphertext encrypted under one provider name
        # cannot be silently swapped into another provider's record.
        ciphertext = AESGCM(self.key).encrypt(nonce, value.encode(), provider.encode())
        return {"nonce": base64.b64encode(nonce).decode(), "ciphertext": base64.b64encode(ciphertext).decode()}

    def decrypt(self, provider: str, record: dict) -> str:
        try:
            return AESGCM(self.key).decrypt(
                base64.b64decode(record["nonce"]), base64.b64decode(record["ciphertext"]), provider.encode()
            ).decode()
        except (InvalidTag, KeyError, ValueError):
            raise CredentialUnavailable() from None


class CredentialStore(Protocol):
    async def set_credential(self, provider: str, kind: CredentialKind, value: str) -> ProviderCredentialRecord: ...
    async def get_secret(self, provider: str) -> str | None: ...
    async def describe(self, provider: str) -> ProviderCredentialRecord | None: ...
    async def list_records(self) -> list[ProviderCredentialRecord]: ...
    async def clear_credential(self, provider: str) -> None: ...


def _record(provider: str, kind: CredentialKind, value: str, updated_at: datetime) -> ProviderCredentialRecord:
    return ProviderCredentialRecord(provider=provider, kind=kind, last_four=value[-4:], updated_at=updated_at)


class InMemoryCredentialStore:
    """Dev/test default. Does not survive a restart — a real deployment
    must configure CODING_AGENT_SECRET_KEY_FILE so EncryptedFileCredentialStore
    is used instead; see app.py's create_app."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}
        self._records: dict[str, ProviderCredentialRecord] = {}

    async def set_credential(self, provider: str, kind: CredentialKind, value: str) -> ProviderCredentialRecord:
        record = _record(provider, kind, value, datetime.now(UTC))
        self._secrets[provider] = value
        self._records[provider] = record
        return record

    async def get_secret(self, provider: str) -> str | None:
        return self._secrets.get(provider)

    async def describe(self, provider: str) -> ProviderCredentialRecord | None:
        return self._records.get(provider)

    async def list_records(self) -> list[ProviderCredentialRecord]:
        return sorted(self._records.values(), key=lambda r: r.provider)

    async def clear_credential(self, provider: str) -> None:
        self._secrets.pop(provider, None)
        self._records.pop(provider, None)


class EncryptedFileCredentialStore:
    """Persists encrypted credentials to one JSON file. Single-writer with
    a coarse in-process lock — this service has no multi-process deployment
    yet, unlike companion-core's Postgres-backed stores, so a plain
    read-modify-write-under-lock is enough."""

    def __init__(self, path: str, keyring: CredentialKeyring) -> None:
        self._path = Path(path)
        self._keyring = keyring
        self._lock = asyncio.Lock()

    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        with self._path.open("r") as handle:
            return json.load(handle)

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with tmp.open("w") as handle:
            json.dump(data, handle)
        os.chmod(tmp, 0o600)
        tmp.replace(self._path)

    async def set_credential(self, provider: str, kind: CredentialKind, value: str) -> ProviderCredentialRecord:
        async with self._lock:
            data = self._read()
            now = datetime.now(UTC)
            data[provider] = {
                "kind": kind.value,
                "last_four": value[-4:],
                "updated_at": now.isoformat(),
                **self._keyring.encrypt(provider, value),
            }
            self._write(data)
            return _record(provider, kind, value, now)

    async def get_secret(self, provider: str) -> str | None:
        async with self._lock:
            entry = self._read().get(provider)
            if entry is None:
                return None
            return self._keyring.decrypt(provider, entry)

    async def describe(self, provider: str) -> ProviderCredentialRecord | None:
        async with self._lock:
            entry = self._read().get(provider)
            if entry is None:
                return None
            return ProviderCredentialRecord(
                provider=provider,
                kind=CredentialKind(entry["kind"]),
                last_four=entry["last_four"],
                updated_at=datetime.fromisoformat(entry["updated_at"]),
            )

    async def list_records(self) -> list[ProviderCredentialRecord]:
        async with self._lock:
            data = self._read()
            return sorted(
                (
                    ProviderCredentialRecord(
                        provider=provider,
                        kind=CredentialKind(entry["kind"]),
                        last_four=entry["last_four"],
                        updated_at=datetime.fromisoformat(entry["updated_at"]),
                    )
                    for provider, entry in data.items()
                ),
                key=lambda r: r.provider,
            )

    async def clear_credential(self, provider: str) -> None:
        async with self._lock:
            data = self._read()
            if data.pop(provider, None) is not None:
                self._write(data)
