"""A note's tag is its place in the owner's folder tree: slash-separated names under the fixed root "All Notes".

`Projects/Project StarWars/Finance` and `All Notes/Projects/Project StarWars/Finance` are the same tag. An untagged note sits directly in All Notes.
The tree is derived from the tags of the notes that exist; there is no separate folder record. The Android client repeats these rules in
`NotesLogic.kt` (`normaliseNoteTag`); change both together.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator

ROOT = "All Notes"
SEPARATOR = "/"
MAX_DEPTH = 5
MAX_SEGMENT_LENGTH = 60


def normalise_tag(raw: Any) -> str | None:
    """Canonical tag, or None for none. Blank segments are dropped, inner whitespace collapses, a leading "All Notes" is the root and not part of the tag."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("a tag must be text")  # noqa: TRY004 - pydantic turns only ValueError into a 422
    segments = [" ".join(part.split()) for part in raw.split(SEPARATOR)]
    segments = [s for s in segments if s]
    if segments and segments[0].casefold() == ROOT.casefold():
        segments = segments[1:]
    if not segments:
        return None
    if len(segments) > MAX_DEPTH:
        raise ValueError(f"a tag can have at most {MAX_DEPTH} levels")
    if any(len(s) > MAX_SEGMENT_LENGTH for s in segments):
        raise ValueError(f"each level of a tag can have at most {MAX_SEGMENT_LENGTH} characters")
    return SEPARATOR.join(segments)


NoteTag = Annotated[str | None, BeforeValidator(normalise_tag)]
