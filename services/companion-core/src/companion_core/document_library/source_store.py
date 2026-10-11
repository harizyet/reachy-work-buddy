"""The authoritative original of every document: write-once, content-addressed by SHA-256 (`sha256/ab/cd/<hash>`), re-verified on read (ADR 0034).

The same bytes are stored once however many Reachy documents point at them. Nothing here knows about policy: the caller (the service) decides who may read and when a blob has no
owner left. The document worker never mounts this directory; it is sent a verified copy over HTTP."""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

_BLOCK = 1 << 20


class SourceCorrupt(Exception):
    """The stored bytes no longer hash to their name (or are missing)."""


class SourceRejected(Exception):
    """The upload was refused before it was committed (too large, wrong type)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class SourceStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        (self.root / "tmp").mkdir(parents=True, exist_ok=True)

    def path_for(self, source_hash: str) -> Path:
        if len(source_hash) != 64 or any(c not in "0123456789abcdef" for c in source_hash):
            raise ValueError("not a sha256")
        return self.root / "sha256" / source_hash[:2] / source_hash[2:4] / source_hash

    def exists(self, source_hash: str) -> bool:
        return self.path_for(source_hash).is_file()

    async def put(
        self, chunks: AsyncIterator[bytes], *, max_bytes: int, head_ok: Callable[[bytes], bool], validate: Callable[[Path], None] | None = None
    ) -> tuple[str, int, bool]:
        """Stream into a temporary file, hash while writing, check the first bytes and (optionally) the whole file, then commit atomically. Returns (hash, size, newly_stored)."""
        tmp = self.root / "tmp" / uuid.uuid4().hex
        digest, size, head = hashlib.sha256(), 0, b""
        try:
            with tmp.open("wb") as out:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > max_bytes:
                        raise SourceRejected(413, "The file is too large")
                    if len(head) < 16:
                        head = (head + chunk)[:16]
                    digest.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if size == 0 or not head_ok(head):
                raise SourceRejected(415, "That file type is not supported")
            if validate is not None:
                validate(tmp)
            final = self.path_for(digest.hexdigest())
            if final.is_file():
                return digest.hexdigest(), size, False
            final.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(tmp, 0o440)
            os.replace(tmp, final)
            return digest.hexdigest(), size, True
        finally:
            tmp.unlink(missing_ok=True)

    async def verify(self, source_hash: str) -> int:
        """Hash the stored file again; raise SourceCorrupt when it is missing or no longer matches. Returns its size."""
        return await asyncio.to_thread(self._verify, source_hash)

    def _verify(self, source_hash: str) -> int:
        path = self.path_for(source_hash)
        digest, size = hashlib.sha256(), 0
        try:
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(_BLOCK), b""):
                    digest.update(block)
                    size += len(block)
        except FileNotFoundError:
            raise SourceCorrupt("source missing") from None
        if digest.hexdigest() != source_hash:
            raise SourceCorrupt("source does not match its hash")
        return size

    async def read_verified(self, source_hash: str) -> bytes:
        """The whole original, verified against its hash before it is returned."""
        return await asyncio.to_thread(self._read_verified, source_hash)

    def _read_verified(self, source_hash: str) -> bytes:
        try:
            data = self.path_for(source_hash).read_bytes()
        except FileNotFoundError:
            raise SourceCorrupt("source missing") from None
        if hashlib.sha256(data).hexdigest() != source_hash:
            raise SourceCorrupt("source does not match its hash")
        return data

    async def delete(self, source_hash: str) -> None:
        await asyncio.to_thread(self._delete, source_hash)

    def _delete(self, source_hash: str) -> None:
        path = self.path_for(source_hash)
        path.unlink(missing_ok=True)
        for parent in (path.parent, path.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                break
