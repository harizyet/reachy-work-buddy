"""Allowlist sanitiser for the HTML MinerU renders from a document (the extraction inspector, owner decision 2026-10-12: sanitise untrusted HTML and CSS as well as sandbox it).

MinerU escapes document text itself, so this is a second, independent layer: whatever the renderer returns is rebuilt from a small set of structural tags and attributes. Scripts, frames,
objects, forms, images, links (kept as plain text), event-handler attributes, inline styles, `javascript:` and any URL are never carried over, and the stylesheet loses `@import` and every
`url()`. The browser then shows the result in a sandboxed frame with a restrictive policy; this module is why that frame has nothing to block."""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser

ALLOWED_TAGS = frozenset(
    ["article", "section", "div", "p", "span", "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col", "ul", "ol", "li", "figure", "figcaption", "pre", "code", "em", "strong", "b", "i", "u", "sup", "sub", "br", "hr", "blockquote", "small", "mark", "dl", "dt", "dd"]
)
VOID_TAGS = frozenset({"br", "hr", "col"})
DROP_WITH_CONTENT = frozenset(["script", "style", "iframe", "frame", "frameset", "object", "embed", "applet", "svg", "math", "template", "noscript", "title", "head", "select", "textarea", "button", "form", "audio", "video", "canvas"])
_CLASS_OK = re.compile(r"^[A-Za-z0-9 _:.-]{0,200}$")
_DATA_OK = re.compile(r"^[A-Za-z0-9 _:.,-]{0,80}$")
_DIGITS = re.compile(r"^\d{1,3}$")
_CSS_URL = re.compile(r"url\s*\([^)]*\)?", re.IGNORECASE)
_CSS_IMPORT = re.compile(r"@import\b[^;{]*;?", re.IGNORECASE)
_CSS_EXPR = re.compile(r"(?:expression|image-set|src)\s*\([^)]*\)?", re.IGNORECASE)
_CSS_DECL_BAD = re.compile(r"(?:behavior|-moz-binding)\s*:[^;}]*;?|javascript\s*:", re.IGNORECASE)


class _Rebuild(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0  # depth inside a tag whose content is dropped

    def handle_starttag(self, tag: str, attrs) -> None:
        if self._skip:
            if tag in DROP_WITH_CONTENT:
                self._skip += 1
            return
        if tag in DROP_WITH_CONTENT:
            self._skip = 1
            return
        if tag == "a":  # a link keeps its text and loses its address
            tag, attrs = "span", [("class", "docvortex-link-text")]
        if tag not in ALLOWED_TAGS:
            return
        kept = []
        for name, value in attrs:
            value = value or ""
            if name == "class" and _CLASS_OK.match(value):
                kept.append(f' class="{escape(value, quote=True)}"')
            elif name.startswith("data-") and re.fullmatch(r"data-[a-z0-9-]{1,40}", name) and _DATA_OK.match(value):
                kept.append(f' {name}="{escape(value, quote=True)}"')
            elif name in ("colspan", "rowspan") and _DIGITS.match(value):
                kept.append(f' {name}="{value}"')
        self.out.append(f"<{tag}{''.join(kept)}>")

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._skip:
            if tag in DROP_WITH_CONTENT:
                self._skip -= 1
            return
        if tag == "a":
            tag = "span"
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.out.append(escape(data, quote=False))

    # comments, declarations and processing instructions are dropped by not overriding handle_comment/handle_decl/handle_pi


def sanitize_fragment(markup: str) -> str:
    parser = _Rebuild()
    parser.feed(markup)
    parser.close()
    return "".join(parser.out)


def sanitize_css(css: str) -> str:
    """Keep the rules, lose anything that can fetch or execute: `@import`, every `url(...)` with its address, expressions, bindings, and every `<` (so nothing can close the style element)."""
    css = css.replace("<", "")
    css = _CSS_IMPORT.sub("", css)
    css = _CSS_URL.sub("none", css)
    css = _CSS_EXPR.sub("none", css)
    return _CSS_DECL_BAD.sub("", css)


def document(css: str, markup: str) -> str:
    """A fragment with its stylesheet, both sanitised, ready to sit in a sandboxed frame."""
    return f"<style>{sanitize_css(css)}</style>{sanitize_fragment(markup)}"
