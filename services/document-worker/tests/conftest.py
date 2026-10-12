from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from document_worker.app import create_app
from document_worker.config import Settings
from document_worker.engine import (
    EngineError,
    EngineHealth,
    LayoutBlock,
    PageLayout,
    ParseSummary,
    RawContent,
    RenderedImage,
    Ticket,
)

TOKEN = "t0ken"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeEngine:
    """An in-memory stand-in for the MinerU library that reproduces the behaviours the 50A spike found: identity is the
    content hash, identical bytes share one document, search is global, and forgetting a file leaves the document row until
    orphans are cleaned."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}  # sha -> {"pages": [...], "status": ..., "files": set(paths)}
        self.paths: dict[str, str] = {}
        self.ready = True
        self.telemetry_disabled = True
        self.fail_with: str | None = None
        self.parse_status = "done"
        self.pages_for: dict[str, list[str]] = {}  # test hook: sha -> page texts (default: derive from file text)
        self.invalidated: list[str] = []
        self.page_ranges: list[tuple[str, str | None]] = []

    def health(self):
        return EngineHealth(self.ready, self.telemetry_disabled, None if self.ready else "not ready")

    def _maybe_fail(self):
        if self.fail_with:
            raise EngineError(self.fail_with)

    def ensure_parse(self, path: Path, tier, page_range, force):
        self._maybe_fail()
        self.page_ranges.append((path.suffix, page_range))
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        text = data.decode("latin-1", errors="ignore")
        pages = self.pages_for.get(sha) or [p for p in text.split("\f")] or [""]
        doc = self.docs.setdefault(sha, {"pages": pages, "files": set(), "status": self.parse_status})
        doc["files"].add(str(path))
        self.paths[str(path)] = sha
        return Ticket(sha, sha[:7])

    def _doc(self, ref):
        for sha, doc in self.docs.items():
            if sha.startswith(ref):
                return sha, doc
        raise EngineError("doc_not_found")

    def parse_summary(self, ref, tier):
        self._maybe_fail()
        _, doc = self._doc(ref)
        return ParseSummary((doc["status"],), "parse_failed" if doc["status"] == "failed" else None)

    def page_count(self, ref):
        return len(self._doc(ref)[1]["pages"])

    def read(self, ref, tier, page_range, after, limit):
        self._maybe_fail()
        _, doc = self._doc(ref)
        if doc["status"] != "done":
            raise EngineError("tier_not_cached")
        want = [int(page_range)] if page_range and page_range.isdigit() else range(1, len(doc["pages"]) + 1)
        body = "\n\n".join(f"<!-- page {n} of {len(doc['pages'])} -->\n\n{doc['pages'][n - 1]}" for n in want)
        n0, n1 = (want[0], want[-1]) if isinstance(want, list) else (1, len(doc["pages"]))
        return RawContent(body, ((f"doc:{ref}/tier:{tier}/page:{n0}", f"doc:{ref}/tier:{tier}/page:{n1}/block:2"),))

    def read_locator(self, locator, context, limit):
        return RawContent(f"locator content for {locator}", ((locator, locator),))

    def page_layout(self, ref, tier, page):
        self._maybe_fail()
        _, doc = self._doc(ref)
        if page > len(doc["pages"]):
            raise EngineError("page_not_cached")
        return PageLayout(595.0, 842.0, (LayoutBlock(1, "text", (0.1, 0.1, 0.9, 0.2)), LayoutBlock(2, "chart", None)))

    def page_html(self, ref, tier, page):
        self._maybe_fail()
        _, doc = self._doc(ref)
        return "<style>.x{}</style><article><p>" + doc["pages"][page - 1].replace("<", "&lt;") + "</p></article>"

    def image(self, ref, tier, page, block, image_format):
        self._maybe_fail()
        if block == 99:
            raise EngineError("block_not_found")
        return RenderedImage(b"\x89PNG-fake-" + f"{page}-{block}".encode(), "image/png" if image_format == "png" else "image/jpeg")

    def structured_export(self, ref, tier, kind, last_page):
        self._maybe_fail()
        return b'{"kind": "' + kind.encode() + b'", "pages": ' + str(last_page).encode() + b"}"

    def invalidate(self, ref, tier):
        self._maybe_fail()
        self._doc(ref)
        self.invalidated.append((ref, tier))

    def forget(self, path):
        self._maybe_fail()
        sha = self.paths.pop(str(path), None)
        if sha is None:
            raise EngineError("file_not_found")
        self.docs[sha]["files"].discard(str(path))

    def cleanup_orphans(self):
        for sha in [s for s, d in self.docs.items() if not d["files"]]:
            del self.docs[sha]

    def has_active_files(self, ref):
        try:
            return bool(self._doc(ref)[1]["files"])
        except EngineError:
            return False


def pdf_bytes(*pages: str) -> bytes:
    return b"%PDF-1.4\n" + "\f".join(pages).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def settings(tmp_path):
    return Settings(token=TOKEN, work_dir=tmp_path / "work", max_upload_bytes=4096, max_pages=5)


@pytest.fixture
def client(engine, settings):
    app = create_app(settings, engine)
    return _Client(app)


class _Client:
    """Synchronous wrapper over the ASGI app (the repo convention is httpx.ASGITransport; this keeps the tests sync)."""

    def __init__(self, app):
        import asyncio

        self.app, self.loop = app, asyncio.new_event_loop()

    def request(self, method, url, **kw):
        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://worker") as c:
                return await c.request(method, url, **kw)

        return self.loop.run_until_complete(go())

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)

    def upload(self, document_id: str, data: bytes, *, tier="basic", extension="pdf", source_hash=None, headers=AUTH):
        return self.post(
            "/documents",
            headers=headers,
            data={"document_id": document_id, "source_hash": source_hash or sha(data), "tier": tier, "extension": extension},
            files={"file": ("x." + extension, data, "application/octet-stream")},
        )
