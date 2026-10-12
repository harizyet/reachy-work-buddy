# Phase 50: MinerU extraction inspector in the Documents tab (2026-10-12)

Owner request: an inspector in the existing Documents tab that reuses MinerU 4.0's own results and renderers, keeps Reachy's security boundary, and creates no second document store. **Built and verified locally; NOT deployed** (production is unchanged and the feature needs a core, hub and worker rebuild, so it waits for the owner's approval).

## What MinerU 4.0.12 already provides (inspected first)

| Need | What MinerU supplies | How it is reused |
|---|---|---|
| Original page picture | doclib `read_content(locator, format="image")`: renders the page, or one block's bbox crop, from the stored source (PDF and image sources only), as an image asset in a temp file | the worker calls it and returns the bytes (the temp file is removed; the path never leaves) |
| Extracted Markdown | doclib `get_doc_content` (markdown with page markers; figure references are backend locators) | the worker returns it with locators rewritten to `#page-N-block-M` |
| Page-by-page layout | the structured result ("middle JSON", schema `docvortex.middle`): pages, blocks (type, index, bbox as fractions of the page), per-page size | read from the parse files the doclib stored, selected with MinerU's own `load_pages_from_done_batches` and loaded with `read_legacy_middle_json`; bboxes go to the browser unchanged |
| Rendered view, tables, formulas | `mineru.render.render(middle_json, RenderFormat.HTML)`; tables render as real tables, formulas as LaTeX | the HTML fragment (`render_html(..., standalone=False)`) plus the stylesheet taken from MinerU's standalone page; the standalone page itself is never sent because it loads MathJax from a public CDN |
| Structured downloads | `render(..., CONTENT_LIST)` and the middle JSON itself | exported as JSON; Markdown from the doclib; HTML as a scriptless self-contained file |
| Gradio WebUI | a separate app that talks to the stateless `/v1` API, with its own PDF viewer | not exposed or reused: it would bypass Reachy's authorization, and the doclib already has everything the inspector needs |

Not offered by MinerU's doclib API (so not built): LaTeX/DOCX/EPUB/PDF exports and `structured_content` are reachable through the render API but were left out to stay lean; the doclib implements Markdown only for `export`.

## Security boundary

* Browser to hub (owner session plus CSRF; the robot bearer is refused; the hub sets the sensitive ceiling itself and drops any browser-supplied one) to core to worker. The upstream WebUI and the worker's API are not exposed.
* Core re-runs the read-path checks on every inspector route before the worker is asked: document exists and is not being deleted, the stored original still matches its hash, the channel ceiling and project allow it, the document is processed. A restricted document makes **no** worker call. The original download needs no worker and works for unprocessed or failed documents, still integrity-checked.
* No worker filesystem path, backend locator, backend reference or library-wide search leaves the worker (tested: markdown refs rewritten, outputs scanned for MinerU's data directory, a worker error code that means "lost document" is no longer used for a missing page, so inspecting a bad page can no longer reset a healthy document).
* The extraction HTML is document-derived, so the browser shows it only in `<iframe sandbox="">` (no scripts, no same-origin, no forms) with an inline `default-src 'none'` policy, and nothing from it is put into the page's own DOM. Downloads are attachments with `nosniff`, `no-store` and a `sandbox` policy for HTML and the original; file names come from the title, never a path.
* No second store: nothing is persisted by the inspector; pictures and structured data are produced on demand from MinerU's cache, and the picture temp files are deleted after reading.

## Hardening added before deployment (owner instruction 2026-10-12)

MinerU escapes document text itself, but the owner asked for sanitising as well as sandboxing, so the HTML and CSS are now rebuilt in the worker (`htmlsafe.py`) from an allowlist: only structural tags (headings, paragraphs, tables, lists, spans and similar), only `class`, `data-*` and `colspan`/`rowspan` attributes; scripts, frames, objects, embeds, forms, media, SVG, MathML, images, `<meta>`, `<link>`, `<base>`, event-handler attributes, inline `style`, and every URL are dropped, and a link keeps its text but loses its address. The stylesheet loses `@import`, every `url(...)`, expressions, bindings and every `<`. The same applies to the HTML export. The browser frame adds three more layers: an empty `sandbox` attribute, an inline policy (`default-src 'none'`; no images, fonts, connections, media, objects, frames, forms or `<base>` href) with `no-referrer`, and a `<base target="_blank">` so a link click opens nothing. Tests: 19 hostile inputs plus structure, escaping and CSS cases in `test_htmlsafe.py`; the exact policy is asserted in the web tests.

**Real-browser proof (not a mock), `e2e/iframe-safety.mjs`:** the real built app, a real signed-in owner session and the real worker, with the page HTML replaced in flight by markup that tries every route out (scripts reading `parent`, `top` and cookies, a fetch to a listener, a fetch of the authenticated `/document-library/documents` API with exfiltration, XHR, `window.open`, an auto-submitted form, `top.location`, `<meta refresh>`, `<link>` and `@import`, `<img onerror>`, nested iframe, object, embed, video, a `<base href>`, and clicks on a top-targeted link and a plain link): 0 requests reached the listener, nothing ran with access to the page, the page never navigated, no popups or dialogs, the parent could not read into the frame, none of the markup entered the page's own DOM, and a `<script>` in the Markdown tab showed as literal text; 18 of 18 checks across desktop and mobile. The ordinary inspector run (`documents-inspector.mjs`) still passes after sanitising, with the table still a real table.

## Verification

* **Worker** (25 tests): layout, markdown rewriting, scriptless HTML, images and block crops with safe headers, no page image for Word files, exports, fail-closed without leaking messages, auth.
* **Core** (57 tests in `test_document_library.py`): inspect shows the document's provenance (hash, tier, `derived_extraction`) and no backend identity; policy, state and integrity are checked before any worker call (a restricted document produced zero worker calls); tampered original refused; images and headers; exports named safely (a hostile title with path and header-injection characters yields a safe name); the original downloads when the worker is down, refuses a restricted or tampered one.
* **Hub** (6 tests in `test_document_library_proxy.py`): anonymous and bearer refused on every inspector route, a sensitive original readable by the owner session with the hub-set ceiling, safe headers passed through, 422s for bad parameters.
* **Web** (18 tests in `documents.test.tsx`, suite 270 passed; typecheck and build clean): split view, tier and page count, block overlay, locked frame and literal markdown, page navigation, block crop, Improve reading, five downloads, no-picture case, failed download, not offered before ready.
* **Real engine and real browser (labelled: not a mock):** a throwaway real hub and core in front of the real worker image with real MinerU (`clients/web/e2e/documents_hub_server.py`, `e2e/documents-inspector.mjs`, needs a running worker, not part of the default suite), headless Chromium at 1280 and 390 pixels: upload, Ready, MinerU's 1654x2339 page picture, the block overlay, the sandboxed frame showing the heading and a real table, a figure crop, the Markdown (table as markdown), the blocks table, page 2 beside its extraction, no horizontal overflow, the five downloads with the right content (Markdown with `#page-1-block-5` and no locators, scriptless HTML, 4-item content list, structured JSON of schema `docvortex.middle` with no data-directory string, the original PDF intact), no console errors. 34 of 34 checks passed on both viewports. Ruff clean; full run 3,068 passed with the four known baseline failures.

## Limits

* Formulas are shown as LaTeX source (no math rendering, because MinerU's HTML would need scripts or a public CDN); a figure appears as its caption in the rendered view and as a picture when its block is selected.
* Block selection is on the picture (and the blocks table); the locked frame cannot be scrolled to a block without scripts.
* Word files have a rendered view, markdown and downloads, but no page picture or block positions.
* The inspector shows one page at a time, up to the worker's page limit (200).
* Not done: deployment, the owner's own browser check, and a check with a large scanned document.
