"""The document file types Reachy accepts (Phase 50, widened for Phase 53), in one place for core (upload) and the document worker (ingest).

Only types that MinerU, as installed in the document worker image, was shown to parse are listed; plain text and Markdown were tried and are NOT parsed by it, so they are not accepted.
What each type gives, measured on 2026-10-14 (docs/verification/phase-53-document-types-2026-10-14.md):

* presentations (pptx, ppt, odp): one page per slide, slide order kept, headings recovered; no page picture;
* spreadsheets (xlsx, xls, ods): one page per sheet, as tables; no page picture;
* word-processor files (docx, doc, rtf, odt), epub, html, csv, tsv: one page (the parser does not paginate them); no page picture;
* pdf and images: real pages (images: one) and page pictures.

A type is accepted by its CONTENT (leading bytes, and for packaged formats the entries that make them that format), never by its name alone."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP = b"PK\x03\x04"
_OOXML = "application/vnd.openxmlformats-officedocument."
_ODF = "application/vnd.oasis.opendocument."


@dataclass(frozen=True)
class DocType:
    mime: str
    kind: str  # pdf | image | zip | ole | rtf | text
    entry: str | None = None  # a zip entry that must exist (OOXML)
    odf_mime: str | None = None  # the text of the `mimetype` entry that must match (ODF, EPUB)
    label: str = ""


TYPES: dict[str, DocType] = {
    "pdf": DocType("application/pdf", "pdf", label="PDF"),
    "png": DocType("image/png", "image", label="PNG image"),
    "jpg": DocType("image/jpeg", "image", label="JPEG image"),
    "docx": DocType(_OOXML + "wordprocessingml.document", "zip", entry="word/document.xml", label="Word"),
    "doc": DocType("application/msword", "ole", label="Word 97–2003"),
    "pptx": DocType(_OOXML + "presentationml.presentation", "zip", entry="ppt/presentation.xml", label="PowerPoint"),
    "ppt": DocType("application/vnd.ms-powerpoint", "ole", label="PowerPoint 97–2003"),
    "xlsx": DocType(_OOXML + "spreadsheetml.sheet", "zip", entry="xl/workbook.xml", label="Excel"),
    "xls": DocType("application/vnd.ms-excel", "ole", label="Excel 97–2003"),
    "rtf": DocType("application/rtf", "rtf", label="Rich Text"),
    "odt": DocType(_ODF + "text", "zip", odf_mime=_ODF + "text", label="OpenDocument text"),
    "odp": DocType(_ODF + "presentation", "zip", odf_mime=_ODF + "presentation", label="OpenDocument presentation"),
    "ods": DocType(_ODF + "spreadsheet", "zip", odf_mime=_ODF + "spreadsheet", label="OpenDocument spreadsheet"),
    "epub": DocType("application/epub+zip", "zip", odf_mime="application/epub+zip", label="EPUB"),
    "html": DocType("text/html", "text", label="HTML"),
    "csv": DocType("text/csv", "text", label="CSV"),
    "tsv": DocType("text/tab-separated-values", "text", label="TSV"),
}
ALIASES = {"jpeg": "jpg", "htm": "html"}
PAGE_PICTURE_TYPES = frozenset({"pdf", "png", "jpg"})  # MinerU renders page and block pictures from PDF and image sources only
PRESENTATION_TYPES = frozenset({"pptx", "ppt", "odp", "pdf"})
# Presentation files the parser was not shown to read: refused with the way forward (export to PDF or PPTX).
UNREAD_PRESENTATIONS = frozenset({"pps", "ppsx", "pptm", "key", "pages", "numbers"})
ACCEPT_ATTRIBUTE = ",".join(f".{e}" for e in (*TYPES, *ALIASES))
MIME_TO_EXTENSION = {t.mime: e for e, t in TYPES.items()}


def normalise_extension(name: str) -> str:
    ext = Path(name.replace("\\", "/")).suffix.lower().lstrip(".")
    return ALIASES.get(ext, ext)


def native_text(ext: str) -> bool:
    """Types that carry their own text, so the fastest reading tier reads them fully; pdf and images may be scans and get OCR."""
    return ext not in ("pdf", "png", "jpg")


def head_ok(ext: str, head: bytes) -> bool:
    """The first bytes are those of this type. Used before the whole file is read."""
    t = TYPES.get(ext)
    if t is None or not head:
        return False
    if t.kind == "pdf":
        return head.startswith(b"%PDF-")
    if t.kind == "image":
        return head.startswith(b"\x89PNG\r\n\x1a\n" if ext == "png" else b"\xff\xd8\xff")
    if t.kind == "zip":
        return head.startswith(_ZIP)
    if t.kind == "ole":
        return head.startswith(_OLE)
    if t.kind == "rtf":
        return head.startswith(b"{\\rtf")
    return b"\x00" not in head  # text: no binary bytes


def file_ok(ext: str, path: Path) -> bool:
    """The whole file is what its type says: a packaged format has the entry that makes it that format, a text type is readable text."""
    t = TYPES.get(ext)
    if t is None:
        return False
    if t.kind == "zip":
        try:
            with zipfile.ZipFile(path) as package:
                names = package.namelist()
                if t.entry is not None:
                    return t.entry in names
                return "mimetype" in names and package.read("mimetype")[:100].decode("ascii", "ignore").strip() == t.odf_mime
        except (zipfile.BadZipFile, KeyError, OSError):
            return False
    if t.kind == "text":
        with path.open("rb") as handle:
            sample = handle.read(8192)
        if b"\x00" in sample:
            return False
        try:
            text = sample[:-4].decode("utf-8")  # the last bytes may cut a character
        except UnicodeDecodeError:
            return False
        return "<" in text if ext == "html" else True
    return True
