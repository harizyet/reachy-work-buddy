"""29.19: provider credential storage, encrypted at rest for the
file-backed implementation. No real HTTP layer needed — routes.py is a
thin pass-through tested separately in test_app.py."""

import asyncio
import base64
import json
import os
import stat
from pathlib import Path

import pytest
from coding_agent_service.credentials import (
    CredentialKeyring,
    CredentialUnavailable,
    EncryptedFileCredentialStore,
    InMemoryCredentialStore,
)

from shared.models.coding_agent import CredentialKind


def _write_key_file(path) -> None:
    path.write_bytes(json.dumps({"key": base64.b64encode(os.urandom(32)).decode()}).encode())
    os.chmod(path, 0o600)


def test_in_memory_store_round_trips_a_credential() -> None:
    async def run() -> None:
        store = InMemoryCredentialStore()
        assert await store.describe("claude-code") is None

        record = await store.set_credential("claude-code", CredentialKind.API_KEY, "sk-ant-abcd1234")
        assert record.last_four == "1234"
        assert record.kind == CredentialKind.API_KEY

        assert await store.get_secret("claude-code") == "sk-ant-abcd1234"
        described = await store.describe("claude-code")
        assert described.last_four == "1234"

        await store.clear_credential("claude-code")
        assert await store.describe("claude-code") is None
        assert await store.get_secret("claude-code") is None

    asyncio.run(run())


def test_encrypted_file_store_persists_across_instances(tmp_path) -> None:
    async def run() -> None:
        key_file = tmp_path / "key.json"
        _write_key_file(key_file)
        keyring = CredentialKeyring.from_file(str(key_file))
        data_path = str(tmp_path / "credentials.json")

        store_a = EncryptedFileCredentialStore(data_path, keyring)
        await store_a.set_credential("claude-code", CredentialKind.API_KEY, "sk-ant-abcd1234")

        # A fresh instance (standing in for a restarted process) must read
        # back the same secret through its own keyring, not a cached one.
        store_b = EncryptedFileCredentialStore(data_path, CredentialKeyring.from_file(str(key_file)))
        assert await store_b.get_secret("claude-code") == "sk-ant-abcd1234"
        records = await store_b.list_records()
        assert len(records) == 1 and records[0].provider == "claude-code"

        # The file on disk never holds the plaintext secret.
        raw = await asyncio.to_thread(Path(data_path).read_text)
        assert "sk-ant-abcd1234" not in raw

    asyncio.run(run())


def test_encrypted_file_store_rejects_wrong_key(tmp_path) -> None:
    async def run() -> None:
        key_file_a = tmp_path / "key-a.json"
        key_file_b = tmp_path / "key-b.json"
        _write_key_file(key_file_a)
        _write_key_file(key_file_b)
        data_path = str(tmp_path / "credentials.json")

        store_a = EncryptedFileCredentialStore(data_path, CredentialKeyring.from_file(str(key_file_a)))
        await store_a.set_credential("claude-code", CredentialKind.API_KEY, "sk-ant-abcd1234")

        store_b = EncryptedFileCredentialStore(data_path, CredentialKeyring.from_file(str(key_file_b)))
        with pytest.raises(CredentialUnavailable):
            await store_b.get_secret("claude-code")

    asyncio.run(run())


def test_keyring_rejects_world_readable_key_file(tmp_path) -> None:
    key_file = tmp_path / "key.json"
    _write_key_file(key_file)
    os.chmod(key_file, 0o644)
    assert os.stat(key_file).st_mode & stat.S_IROTH

    with pytest.raises(CredentialUnavailable):
        CredentialKeyring.from_file(str(key_file))


def test_keyring_rejects_missing_file() -> None:
    with pytest.raises(CredentialUnavailable):
        CredentialKeyring.from_file("/nonexistent/key.json")
