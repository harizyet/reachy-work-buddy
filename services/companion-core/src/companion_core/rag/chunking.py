"""Naive chunking — same honesty-about-scope as this codebase's other
placeholder matchers: splits on markdown-style '#' headings for section
provenance, and on blank lines within a section for chunk boundaries,
packing consecutive paragraphs up to a soft size cap. No real document
structure parsing (no PDF/DOCX support) — a document without markdown
headings just gets `section=None` chunks.
"""

from __future__ import annotations

_MAX_CHUNK_CHARS = 800


def split_into_chunks(content: str) -> list[tuple[str | None, str]]:
    """Returns (section, text) pairs in document order."""
    section: str | None = None
    paragraphs: list[tuple[str | None, str]] = []
    current: list[str] = []

    def flush_paragraph() -> None:
        if current:
            paragraphs.append((section, "\n".join(current)))
            current.clear()

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush_paragraph()
            section = stripped.lstrip("#").strip() or None
        elif stripped == "":
            flush_paragraph()
        else:
            current.append(line)
    flush_paragraph()

    chunks: list[tuple[str | None, str]] = []
    current_section: str | None = None
    current_text = ""
    for para_section, para_text in paragraphs:
        starts_new_chunk = para_section != current_section or (
            current_text and len(current_text) + len(para_text) + 2 > _MAX_CHUNK_CHARS
        )
        if starts_new_chunk:
            if current_text:
                chunks.append((current_section, current_text.strip()))
            current_section = para_section
            current_text = para_text
        else:
            current_text = f"{current_text}\n\n{para_text}"
    if current_text:
        chunks.append((current_section, current_text.strip()))

    return chunks
