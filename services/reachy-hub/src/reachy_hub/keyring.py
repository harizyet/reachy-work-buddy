"""AESGCM keyring for encrypting owner-recognition benchmark captures at
rest (Phase 26d, docs/phase-26.md's benchmark-vs-operational data policy).

Deliberately duplicates the shape of `companion_core.secrets.Keyring`
rather than importing it: ADR 0001 forbids sibling-service runtime
imports (only test code may reach across services). reachy-hub's needs
are simpler than core's — encrypting bytes on disk, no Postgres rows, no
rotation batch job yet — so this is a smaller module, not a copy-paste of
the whole file.
"""

from __future__ import annotations

import base64
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class KeyringUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Encryption key unavailable; check SECRET_KEY_FILE and its permissions")


@dataclass(frozen=True)
class Keyring:
    active: str
    keys: dict[str, bytes] = field(repr=False)

    @classmethod
    def from_file(cls, path: str | None = None) -> Keyring:
        try:
            target = Path(path or os.environ["SECRET_KEY_FILE"])
            # Read the same descriptor whose permissions were checked.
            with target.open("rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                    raise ValueError("permissions")
                data = json.load(stream)
            if not isinstance(data, dict) or not isinstance(data.get("keys"), dict):
                raise TypeError("format")
            keys = {
                name: base64.b64decode(value, validate=True)
                for name, value in data["keys"].items()
            }
            if (
                not keys or data["active"] not in keys
                or any(not isinstance(name, str) or not name or len(value) != 32
                       for name, value in keys.items())
            ):
                raise ValueError("keys")
            return cls(data["active"], keys)
        except (OSError, KeyError, ValueError, TypeError):
            raise KeyringUnavailable() from None

    def encrypt(self, aad: bytes, plaintext: bytes) -> dict:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self.keys[self.active]).encrypt(nonce, plaintext, aad)
        return {"key_id": self.active, "nonce": nonce, "ciphertext": ciphertext}

    def decrypt(self, aad: bytes, record: dict) -> bytes:
        try:
            return AESGCM(self.keys[record["key_id"]]).decrypt(
                bytes(record["nonce"]), bytes(record["ciphertext"]), aad,
            )
        except (InvalidTag, KeyError, ValueError, TypeError):
            raise KeyringUnavailable() from None
