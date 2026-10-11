"""The note tag rules (shared/models/note_tag.py); the Android copy in NotesLogic.kt must agree with these cases."""

import pytest

from shared.models.note_tag import normalise_tag


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("  /  ", None),
        ("All Notes", None),
        ("Meeting Notes", "Meeting Notes"),
        ("All Notes/Meeting Notes", "Meeting Notes"),
        ("all notes/Projects/Project StarWars/Finance", "Projects/Project StarWars/Finance"),
        (" Projects // Project   StarWars /Finance/ ", "Projects/Project StarWars/Finance"),
        ("Projects/All Notes", "Projects/All Notes"),  # only a leading root is the root
        ("a\nb/c\td", "a b/c d"),
    ],
)
def test_tags_are_normalised(raw, expected):
    assert normalise_tag(raw) == expected


def test_depth_and_length_are_bounded():
    assert normalise_tag("a/b/c/d/e") == "a/b/c/d/e"
    with pytest.raises(ValueError):
        normalise_tag("a/b/c/d/e/f")
    assert normalise_tag("x" * 60) == "x" * 60
    with pytest.raises(ValueError):
        normalise_tag("x" * 61)
    with pytest.raises(ValueError):
        normalise_tag(5)
