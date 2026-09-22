from __future__ import annotations

import asyncio

import pytest
from reachy_hub.robot_credential_store import (
    InMemoryRobotCredentialStore,
    load_from_env,
)


def test_verify_accepts_provisioned_token() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision("nano-1", "secret-token")
    assert asyncio.run(store.verify("nano-1", "secret-token")) is True


def test_verify_rejects_wrong_token() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision("nano-1", "secret-token")
    assert asyncio.run(store.verify("nano-1", "wrong-token")) is False


def test_verify_rejects_unknown_robot_id() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision("nano-1", "secret-token")
    assert asyncio.run(store.verify("someone-else", "secret-token")) is False


def test_revoke_removes_access() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision("nano-1", "secret-token")
    store.revoke("nano-1")
    assert asyncio.run(store.verify("nano-1", "secret-token")) is False


def test_stored_tokens_are_hashed_not_plaintext() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision("nano-1", "secret-token")
    assert "secret-token" not in store._hashed_tokens["nano-1"]  # white-box: PBKDF2 output, not the raw value


def test_load_from_env_missing_var_yields_empty_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROBOT_TOKENS", raising=False)
    store = load_from_env()
    assert asyncio.run(store.verify("anything", "anything")) is False


def test_load_from_env_parses_and_hashes_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROBOT_TOKENS", '{"nano-1": "tok-a", "desk-1": "tok-b"}')
    store = load_from_env()
    assert asyncio.run(store.verify("nano-1", "tok-a")) is True
    assert asyncio.run(store.verify("desk-1", "tok-b")) is True
    assert asyncio.run(store.verify("nano-1", "tok-b")) is False


def test_load_from_env_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROBOT_TOKENS", "not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_from_env()


def test_load_from_env_rejects_non_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROBOT_TOKENS", "[1, 2, 3]")
    with pytest.raises(ValueError, match="JSON object"):
        load_from_env()


def test_load_from_env_rejects_empty_token_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROBOT_TOKENS", '{"nano-1": ""}')
    with pytest.raises(ValueError, match="non-empty string token"):
        load_from_env()
