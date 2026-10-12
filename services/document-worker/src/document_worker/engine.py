"""The seam to the document backend. `DocumentEngine` is what the service needs, in plain types; `DoclibEngine` is the one
MinerU implementation and is the only module that imports MinerU (lazily, so tests and the workspace never need it).

Backend errors are reduced to a short code here so a message (which can carry a filesystem path) never leaves the worker.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class EngineError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Ticket:
    sha256: str
    backend_ref: str


@dataclass(frozen=True)
class ParseSummary:
    statuses: tuple[str, ...]  # statuses of the current (non-superseded) parses at this tier: pending/parsing/done/failed
    error_code: str | None = None


@dataclass(frozen=True)
class RawContent:
    content: str
    ranges: tuple[tuple[str, str], ...] = ()
    truncated: bool = False
    next_page_range: str | None = None
    next_after: str | None = None


@dataclass(frozen=True)
class RawHit:
    backend_ref: str
    snippet: str


@dataclass(frozen=True)
class EngineHealth:
    ready: bool
    telemetry_disabled: bool
    detail: str | None = None


class DocumentEngine(Protocol):
    def health(self) -> EngineHealth: ...
    def ensure_parse(self, path: Path, tier: str, page_range: str | None, force: bool) -> Ticket: ...
    def parse_summary(self, backend_ref: str, tier: str) -> ParseSummary: ...
    def page_count(self, backend_ref: str) -> int | None: ...
    def read(self, backend_ref: str, tier: str, page_range: str | None, after: str | None, limit: int) -> RawContent: ...
    def read_locator(self, locator: str, context: int, limit: int) -> RawContent: ...
    def search(self, query: str, limit: int, offset: int) -> tuple[list[RawHit], int]: ...
    def invalidate(self, backend_ref: str, tier: str) -> None: ...
    def forget(self, path: Path) -> None: ...
    def cleanup_orphans(self) -> None: ...
    def has_active_files(self, backend_ref: str) -> bool: ...


@dataclass
class DoclibEngine:
    """MinerU 4.x `DoclibClient` over its Unix socket, which stays inside this container."""

    managed_tier: str = "standard"
    _client: object | None = field(default=None, init=False, repr=False)

    def _api(self):
        from mineru.doclib.client import DoclibClient

        if self._client is None:
            self._client = DoclibClient()
        return self._client

    @staticmethod
    def _wrap(exc: Exception) -> EngineError:
        return EngineError(str(getattr(exc, "code", None) or "engine_error"))

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except EngineError:
            raise
        except Exception as exc:  # noqa: BLE001 - every backend failure becomes a coded EngineError
            raise self._wrap(exc) from None

    def start(self) -> None:
        """Start the doclib server if it is not running, disable telemetry and enable the local managed parse server."""
        from mineru.doclib.types import ConfigSetRequest

        try:
            self._api().get_server_status()
        except Exception:  # noqa: BLE001
            self._client = None
            subprocess.run(["mineru", "server", "start"], check=False, capture_output=True, timeout=120)
            self._wait_for_server()
        api = self._api()
        self._call(api.telemetry_action, "disable")
        for key, value in (("parse_server.local.mode", "managed"), ("parse_server.local.managed_tier", self.managed_tier)):
            self._call(api.set_config, key, ConfigSetRequest(value=value))

    def _wait_for_server(self, seconds: float = 90.0) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                self._api().get_server_status()
                return
            except Exception:  # noqa: BLE001 - the socket appears a few seconds after `server start` returns
                self._client = None  # a client built before the server existed keeps the missing endpoint
                time.sleep(1)
        raise EngineError("engine_unavailable")

    def health(self) -> EngineHealth:
        try:
            api = self._api()
            status = api.get_server_status()
            telemetry = api.get_telemetry_status().state
            local = status.parse_server.local if hasattr(status, "parse_server") else None
            ready = bool(status.running and (local is None or local.healthy))
            return EngineHealth(ready, telemetry == "disabled", None if ready else "parse server not ready")
        except Exception as exc:  # noqa: BLE001
            self._client = None  # re-discover the endpoint if the server was restarted
            return EngineHealth(False, False, str(getattr(exc, "code", "engine_unavailable")))

    def ensure_parse(self, path: Path, tier: str, page_range: str | None, force: bool) -> Ticket:
        from mineru.doclib.types import ParseRequest

        response = self._call(self._api().ensure_parse, ParseRequest(path=str(path), tier=tier, page_range=page_range, force=force))
        return Ticket(response.sha256, response.short_id or response.sha256[:7])

    def parse_summary(self, backend_ref: str, tier: str) -> ParseSummary:
        listing = self._call(self._api().list_parses, doc_ref=backend_ref, tier=tier)
        errors = [p.error_code for p in listing.parses if p.error_code]
        return ParseSummary(tuple(p.status for p in listing.parses), errors[0] if errors else None)

    def page_count(self, backend_ref: str) -> int | None:
        return self._call(self._api().get_doc, backend_ref).page_count

    @staticmethod
    def _raw(response) -> RawContent:
        nxt = response.next_request
        return RawContent(
            response.content,
            tuple((r.start, r.end) for r in response.content_ranges),
            response.truncated,
            nxt.page_range if nxt else None,
            nxt.after if nxt else None,
        )

    def read(self, backend_ref, tier, page_range, after, limit):
        return self._raw(self._call(self._api().get_doc_content, backend_ref, tier=tier, page_range=page_range, after=after, limit=limit))

    def read_locator(self, locator, context, limit):
        return self._raw(self._call(self._api().read_content, locator, context=context, limit=limit))

    def search(self, query, limit, offset):
        response = self._call(self._api().search, query, limit=limit, offset=offset)
        return [RawHit(r.short_id, r.snippet) for r in response.results], response.total

    def invalidate(self, backend_ref: str, tier: str) -> None:
        """Drop the cached parse of ONE tier. Identical bytes share a backend document, so invalidating every tier would also remove what another Reachy document of the same bytes is using."""
        from mineru.doclib.types import InvalidateRequest

        self._call(self._api().invalidate, InvalidateRequest(target="parses", doc_ref=backend_ref, tier=tier))

    def forget(self, path: Path) -> None:
        from mineru.doclib.types import ForgetPathRequest

        self._call(self._api().forget_path, ForgetPathRequest(path=str(path), dry_run=False))

    def cleanup_orphans(self) -> None:
        from mineru.doclib.types import CleanupOrphansRequest

        self._call(self._api().cleanup_orphan_docs, CleanupOrphansRequest(dry_run=False))

    def has_active_files(self, backend_ref: str) -> bool:
        try:
            doc = self._api().get_doc(backend_ref, expand_files=True)
        except Exception:  # noqa: BLE001 - a missing document has no files
            return False
        return any(f.status == "active" for f in (doc.files or []))
