"""A minimal, deterministic PDF writer for meeting minutes (Phase 55, ADR 0039). Standard-library only.

Courier and Courier-Bold are two of the 14 standard PDF fonts, so nothing is embedded; text is encoded as WinAnsi (cp1252). Text the encoding cannot hold raises `PdfError` instead of
being dropped or replaced, and the owner can send the message without the attachment. No creation date or id is written, so the same blocks always give the same bytes (the approval hash
covers the attachment's SHA-256). A richer layout (a proportional font, other scripts) would need a PDF library and is deliberately a separate change."""

from __future__ import annotations

import textwrap

PAGE_W, PAGE_H = 595, 842  # A4 in points
MARGIN = 54
FONT = 10
LEAD = 13
CHARS = 84  # Courier is 600/1000 em: (595 - 2 * 54) / 6 = 81 at 10 pt; wrap a little under
LINES_PER_PAGE = int((PAGE_H - 2 * MARGIN - 20) / LEAD)

Block = tuple[str, str]  # ("title" | "h" | "p" | "li" | "quote" | "gap", text)


class PdfError(ValueError):
    pass


def _enc(text: str) -> bytes:
    try:
        raw = text.encode("cp1252")
    except UnicodeEncodeError as exc:
        bad = text[exc.start:exc.end]
        raise PdfError(f"the PDF cannot hold the character {bad!r}; send the message without the attachment or edit the text") from None
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _lines(blocks: list[Block]) -> list[tuple[str, str]]:
    """(font, text) per output line, already wrapped."""
    out: list[tuple[str, str]] = []
    for kind, text in blocks:
        if kind == "gap":
            out.append(("F1", ""))
            continue
        bold = kind in ("title", "h")
        indent, first, width = ("", "", CHARS)
        if kind == "li":
            first, indent, width = "- ", "  ", CHARS - 2
        elif kind == "quote":
            first, indent, width = "> ", "  ", CHARS - 2
        for n, paragraph in enumerate(str(text).split("\n")):
            wrapped = textwrap.wrap(paragraph, width=width, break_long_words=True, break_on_hyphens=False) or [""]
            for i, line in enumerate(wrapped):
                out.append(("F2" if bold else "F1", (first if (n == 0 and i == 0) else indent) + line))
        if kind in ("title", "h"):
            out.append(("F1", ""))
    return out


def render(title: str, blocks: list[Block]) -> bytes:
    lines = _lines(blocks)
    pages = [lines[i:i + LINES_PER_PAGE] for i in range(0, max(len(lines), 1), LINES_PER_PAGE)] or [[]]
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
    add(b"")  # 2: pages, filled in below
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")  # 3
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold /Encoding /WinAnsiEncoding >>")  # 4
    info = add(b"<< /Title (" + _enc(title[:120]) + b") /Producer (Reachy) >>")  # 5
    kids: list[int] = []
    for number, page in enumerate(pages, 1):
        stream = bytearray()
        y = PAGE_H - MARGIN
        for font, text in page:
            stream += b"BT /" + font.encode() + b" %d Tf %d %d Td (" % (FONT, MARGIN, y) + _enc(text) + b") Tj ET\n"
            y -= LEAD
        stream += b"BT /F1 8 Tf %d %d Td (" % (MARGIN, MARGIN - 24) + _enc(f"Page {number} of {len(pages)}") + b") Tj ET\n"
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + bytes(stream) + b"endstream")
        kids.append(add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>" % (PAGE_W, PAGE_H, content)))
    objects[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, info, xref)
    return bytes(out)
