"""The extraction inspector's view of MinerU 4.x (the only other module that imports MinerU, lazily).

Nothing is parsed or formatted here: the structured result is the middle JSON MinerU stored for the parse, loaded with MinerU's own loader (`load_pages_from_done_batches`,
`read_legacy_middle_json`), and every output comes from MinerU's public renderers (`mineru.render.render` for HTML and content lists) or its doclib page-image rendering (`read_content`
with `format="image"`). The doclib API itself offers only markdown and images, so the structured result is read from the parse files the doclib wrote, using the doclib's own helper to
choose the right batches. Anything that could reveal where MinerU keeps files is checked for before it leaves.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from document_worker import htmlsafe
from document_worker.engine import EngineError, LayoutBlock, PageLayout, RenderedImage

_STYLE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.IGNORECASE | re.DOTALL)
_IMAGE_MIME = {"image/png", "image/jpeg", "image/webp"}
_MAX_RESULTS = 4  # parsed results kept in memory (a document at a tier each)


class _Result:
    def __init__(self, middle, sizes: dict[int, tuple[float, float]], css: str) -> None:
        self.middle = middle
        self.sizes = sizes
        self.css = css


_cache: dict[tuple, _Result] = {}


class Inspector:
    def __init__(self, api) -> None:
        self.api = api

    # --- the stored structured result --------------------------------------------------------------------------

    def _result(self, backend_ref: str, tier: str) -> _Result:
        from mineru.backend.postprocess.legacy_middle_json import (
            read_legacy_middle_json,
        )
        from mineru.config import config
        from mineru.doclib.services.parse_svc import (
            load_pages_from_done_batches,
            parse_batch_json_path,
        )
        from mineru.render import RenderFormat, render

        sha = self.api.get_doc(backend_ref).sha256
        parses = self.api.list_parses(doc_ref=backend_ref, tier=tier, status="done", limit=200).parses
        rows = sorted(({"page_range": p.page_range, "done_at": p.done_at or 0} for p in parses), key=lambda r: r["done_at"], reverse=True)
        if not rows:
            raise EngineError("not_cached")
        key = (sha, tier, tuple((r["page_range"], r["done_at"]) for r in rows))
        if key in _cache:
            return _cache[key]
        data_dir = os.path.expanduser(config.doclib.data_dir)
        pages = load_pages_from_done_batches(data_dir, sha, tier, rows)
        if not pages:
            raise EngineError("not_cached")
        sizes: dict[int, tuple[float, float]] = {}
        newest = None
        for row in rows:
            path = Path(parse_batch_json_path(data_dir, sha, tier, row["page_range"], row["done_at"]))
            if not path.is_file():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            if newest is None:
                newest = read_legacy_middle_json(raw)
            for entry in (raw.get("extensions", {}).get("docvortex_layout", {}) or {}).get("pages", []):
                sizes.setdefault(int(entry["page_idx"]), (float(entry["width_pt"]), float(entry["height_pt"])))
        if newest is None:
            raise EngineError("not_cached")
        middle = newest.model_copy(update={"pages": pages})
        standalone = render(middle, RenderFormat.HTML)  # MinerU's own stylesheet comes with its standalone page; the page's scripts (a CDN math library) are never used
        css = "".join(_STYLE.findall(standalone))  # the rules only; htmlsafe.sanitize_css strips anything that could fetch or execute
        result = _Result(middle, sizes, css)
        while len(_cache) >= _MAX_RESULTS:
            _cache.pop(next(iter(_cache)))
        _cache[key] = result
        return result

    @staticmethod
    def _page(result: _Result, page: int):
        found = next((p for p in result.middle.pages if p.page_idx == page - 1), None)
        if found is None:
            raise EngineError("page_not_cached")
        return found

    @staticmethod
    def _no_paths(payload: bytes) -> bytes:
        from mineru.config import config

        root = os.path.expanduser(config.doclib.data_dir).encode()
        if root and root in payload:
            raise EngineError("unsafe_output")  # an output that names where MinerU keeps files is never sent
        return payload

    # --- per page ------------------------------------------------------------------------------------------------

    def page_layout(self, backend_ref: str, tier: str, page: int) -> PageLayout:
        result = self._result(backend_ref, tier)
        found = self._page(result, page)
        width, height = result.sizes.get(page - 1, (None, None))
        blocks = tuple(
            LayoutBlock(block=b.index + 1, type=str(getattr(b.type, "value", b.type)), bbox=tuple(float(v) for v in b.bbox) if getattr(b, "bbox", None) else None)  # type: ignore[arg-type]
            for b in found.blocks
        )
        return PageLayout(width, height, blocks)

    def page_html(self, backend_ref: str, tier: str, page: int) -> str:
        from mineru.render.html import render_html

        result = self._result(backend_ref, tier)
        one = result.middle.model_copy(update={"pages": [self._page(result, page)]})
        return htmlsafe.document(result.css, render_html(one, standalone=False))  # rebuilt from an allowlist; MinerU's own escaping is not the only line of defence

    def image(self, backend_ref: str, tier: str, page: int, block: int | None, image_format: str) -> RenderedImage:
        locator = f"doc:{backend_ref}/tier:{tier}/page:{page}" + (f"/block:{block}" if block else "")
        response = self.api.read_content(locator, format="image", image_format=image_format)
        asset = response.asset
        if asset is None or asset.mime_type not in _IMAGE_MIME:
            raise EngineError("asset_not_available")
        path = Path(asset.path)
        try:
            data = path.read_bytes()
        finally:
            path.unlink(missing_ok=True)  # the doclib renders into a temporary file; the bytes are all that is kept
        return RenderedImage(data, asset.mime_type)

    # --- whole document ------------------------------------------------------------------------------------------

    def structured_export(self, backend_ref: str, tier: str, kind: str, last_page: int) -> bytes:
        from mineru.render import RenderFormat, render
        from mineru.render.html import render_html

        result = self._result(backend_ref, tier)
        pages = [p for p in result.middle.pages if p.page_idx < last_page]
        middle = result.middle.model_copy(update={"pages": pages})
        if kind == "content_list":
            payload = json.dumps(render(middle, RenderFormat.CONTENT_LIST), ensure_ascii=False, indent=2).encode()
        elif kind == "middle_json":
            payload = json.dumps(middle.model_dump(mode="json"), ensure_ascii=False, indent=2).encode()
        elif kind == "html":
            payload = (
                '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
                f"</head><body>{htmlsafe.document(result.css, render_html(middle, standalone=False))}</body></html>"
            ).encode()
        else:
            raise EngineError("invalid_request")
        return self._no_paths(payload)
