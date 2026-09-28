"""FilesystemEnrollmentStore (Phase 25a.2/25b.3 portal skeleton)."""

import asyncio

import pytest
from reachy_hub.enrollment_store import (
    FilesystemEnrollmentStore,
    InMemoryEnrollmentStore,
    SampleRejected,
)

from shared.models.enrollment import EnrollmentSampleKind


@pytest.mark.parametrize("make_store", [lambda tmp: FilesystemEnrollmentStore(tmp), lambda tmp: InMemoryEnrollmentStore()])
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


def test_filesystem_store_rejects_path_traversal_delete(tmp_path):
    async def run():
        store = FilesystemEnrollmentStore(tmp_path)
        await store.add_sample(EnrollmentSampleKind.VOICE, "audio/wav", b"abc")
        for malicious in ("../face/whatever", "..", ".", "a/b"):
            assert await store.delete_sample(EnrollmentSampleKind.VOICE, malicious) is False

    asyncio.run(run())


def test_filesystem_store_survives_reconstruction(tmp_path):
    async def run():
        first = FilesystemEnrollmentStore(tmp_path)
        sample = await first.add_sample(EnrollmentSampleKind.FACE, "image/jpeg", b"jpeg-bytes")
        second = FilesystemEnrollmentStore(tmp_path)
        listed = await second.list_samples(EnrollmentSampleKind.FACE)
        assert [s.sample_id for s in listed] == [sample.sample_id]

    asyncio.run(run())


@pytest.mark.parametrize("make_store", [lambda tmp: FilesystemEnrollmentStore(tmp), lambda tmp: InMemoryEnrollmentStore()])
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
        store = FilesystemEnrollmentStore(tmp_path)
        for _ in range(3):
            await store.add_sample(EnrollmentSampleKind.VOICE, "audio/wav", b"abc")
        assert await store.delete_all(EnrollmentSampleKind.VOICE) == 3
        assert await store.list_samples(EnrollmentSampleKind.VOICE) == []

    asyncio.run(run())
