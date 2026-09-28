"""FilesystemEnrollmentStore / InMemoryEnrollmentStore (Phase 25a.2/25b.3
portal skeleton, Phase 26d benchmark-vs-operational data policy)."""

import asyncio
import base64
import json
import os

import pytest
from reachy_hub.enrollment_store import (
    FilesystemEnrollmentStore,
    InMemoryEnrollmentStore,
    SampleRejected,
)
from reachy_hub.keyring import Keyring, KeyringUnavailable

from shared.models.enrollment import EnrollmentSampleKind


def _make_keyring() -> Keyring:
    return Keyring("key-1", {"key-1": os.urandom(32)})


def _make_key_file(tmp_path) -> str:
    path = tmp_path / "secret-keys.json"
    path.write_text(json.dumps({
        "active": "key-1",
        "keys": {"key-1": base64.b64encode(os.urandom(32)).decode()},
    }))
    os.chmod(path, 0o600)
    return str(path)


def _filesystem_store(tmp_path):
    return FilesystemEnrollmentStore(tmp_path / "store", _make_keyring())


@pytest.mark.parametrize("make_store", [_filesystem_store, lambda tmp: InMemoryEnrollmentStore()])
def test_add_list_delete_roundtrip(tmp_path, make_store):
    async def run():
        store = make_store(tmp_path)
        sample = await store.add_sample(EnrollmentSampleKind.VOICE, "audio/wav", b"abc")
        assert sample.size_bytes == 3
        listed = await store.list_samples(EnrollmentSampleKind.VOICE)
        assert [s.sample_id for s in listed] == [sample.sample_id]
        assert await store.list_samples(EnrollmentSampleKind.FACE) == []
        assert await store.delete_sample(EnrollmentSampleKind.VOICE, sample.sample_id) is True
        assert await store.delete_sample(EnrollmentSampleKind.VOICE, sample.sample_id) is False
        assert await store.list_samples(EnrollmentSampleKind.VOICE) == []

    asyncio.run(run())


@pytest.mark.parametrize("make_store", [_filesystem_store, lambda tmp: InMemoryEnrollmentStore()])
def test_read_sample_round_trips_original_bytes(tmp_path, make_store):
    async def run():
        store = make_store(tmp_path)
        sample = await store.add_sample(EnrollmentSampleKind.FACE, "image/jpeg", b"jpeg-bytes")
        assert await store.read_sample(EnrollmentSampleKind.FACE, sample.sample_id) == b"jpeg-bytes"
        assert await store.read_sample(EnrollmentSampleKind.FACE, "missing") is None

    asyncio.run(run())


def test_filesystem_store_encrypts_at_rest(tmp_path):
    async def run():
        store = _filesystem_store(tmp_path)
        sample = await store.add_sample(EnrollmentSampleKind.VOICE, "audio/wav", b"a distinctive plaintext payload")
        on_disk = (tmp_path / "store" / "voice" / sample.sample_id).read_bytes()
        assert b"distinctive plaintext" not in on_disk

    asyncio.run(run())


def test_filesystem_store_rejects_wrong_key(tmp_path):
    async def run():
        store_dir = tmp_path / "store"
        writer = FilesystemEnrollmentStore(store_dir, _make_keyring())
        sample = await writer.add_sample(EnrollmentSampleKind.VOICE, "audio/wav", b"abc")
        reader = FilesystemEnrollmentStore(store_dir, _make_keyring())
        with pytest.raises(KeyringUnavailable):
            await reader.read_sample(EnrollmentSampleKind.VOICE, sample.sample_id)

    asyncio.run(run())


def test_filesystem_store_rejects_path_traversal_delete(tmp_path):
    async def run():
        store = _filesystem_store(tmp_path)
        await store.add_sample(EnrollmentSampleKind.VOICE, "audio/wav", b"abc")
        for malicious in ("../face/whatever", "..", ".", "a/b"):
            assert await store.delete_sample(EnrollmentSampleKind.VOICE, malicious) is False

    asyncio.run(run())


def test_filesystem_store_survives_reconstruction(tmp_path):
    async def run():
        keyring = _make_keyring()
        store_dir = tmp_path / "store"
        first = FilesystemEnrollmentStore(store_dir, keyring)
        sample = await first.add_sample(EnrollmentSampleKind.FACE, "image/jpeg", b"jpeg-bytes")
        second = FilesystemEnrollmentStore(store_dir, keyring)
        listed = await second.list_samples(EnrollmentSampleKind.FACE)
        assert [s.sample_id for s in listed] == [sample.sample_id]
        assert await second.read_sample(EnrollmentSampleKind.FACE, sample.sample_id) == b"jpeg-bytes"

    asyncio.run(run())


@pytest.mark.parametrize("make_store", [_filesystem_store, lambda tmp: InMemoryEnrollmentStore()])
def test_rejects_unsupported_content_type_and_oversize(tmp_path, make_store):
    async def run():
        store = make_store(tmp_path)
        with pytest.raises(SampleRejected):
            await store.add_sample(EnrollmentSampleKind.VOICE, "text/plain", b"abc")
        with pytest.raises(SampleRejected):
            await store.add_sample(EnrollmentSampleKind.VOICE, "audio/wav", b"")
        with pytest.raises(SampleRejected):
            await store.add_sample(EnrollmentSampleKind.VOICE, "audio/wav", b"a" * (11 * 1024 * 1024))

    asyncio.run(run())


def test_delete_all(tmp_path):
    async def run():
        store = _filesystem_store(tmp_path)
        for _ in range(3):
            await store.add_sample(EnrollmentSampleKind.VOICE, "audio/wav", b"abc")
        assert await store.delete_all(EnrollmentSampleKind.VOICE) == 3
        assert await store.list_samples(EnrollmentSampleKind.VOICE) == []

    asyncio.run(run())


@pytest.mark.parametrize("make_store", [_filesystem_store, lambda tmp: InMemoryEnrollmentStore()])
def test_benchmark_enabled_defaults_off_and_toggles(tmp_path, make_store):
    async def run():
        store = make_store(tmp_path)
        assert await store.is_benchmark_enabled() is False
        await store.set_benchmark_enabled(True)
        assert await store.is_benchmark_enabled() is True
        await store.set_benchmark_enabled(False)
        assert await store.is_benchmark_enabled() is False

    asyncio.run(run())


def test_benchmark_enabled_survives_filesystem_reconstruction(tmp_path):
    async def run():
        keyring = _make_keyring()
        store_dir = tmp_path / "store"
        first = FilesystemEnrollmentStore(store_dir, keyring)
        await first.set_benchmark_enabled(True)
        second = FilesystemEnrollmentStore(store_dir, keyring)
        assert await second.is_benchmark_enabled() is True

    asyncio.run(run())


def test_keyring_from_file_round_trip(tmp_path):
    path = _make_key_file(tmp_path)
    keyring = Keyring.from_file(path)
    record = keyring.encrypt(b"aad", b"plaintext")
    assert keyring.decrypt(b"aad", record) == b"plaintext"
    with pytest.raises(KeyringUnavailable):
        keyring.decrypt(b"different-aad", record)


def test_keyring_from_file_rejects_group_readable_file(tmp_path):
    path = tmp_path / "secret-keys.json"
    path.write_text(json.dumps({
        "active": "key-1",
        "keys": {"key-1": base64.b64encode(os.urandom(32)).decode()},
    }))
    os.chmod(path, 0o640)
    with pytest.raises(KeyringUnavailable):
        Keyring.from_file(str(path))


def test_keyring_from_file_missing_raises() -> None:
    with pytest.raises(KeyringUnavailable):
        Keyring.from_file("/nonexistent/path.json")
