from companion_core.rag.chunking import split_into_chunks


def test_plain_text_has_no_section() -> None:
    chunks = split_into_chunks("just some plain text\nwith two lines")
    assert len(chunks) == 1
    section, text = chunks[0]
    assert section is None
    assert "plain text" in text


def test_markdown_headings_become_sections() -> None:
    content = "# Intro\nfirst paragraph\n\n## Details\nsecond paragraph"
    chunks = split_into_chunks(content)
    sections = [section for section, _ in chunks]
    assert "Intro" in sections
    assert "Details" in sections


def test_blank_lines_separate_paragraphs_within_a_section() -> None:
    content = "# Section\npara one\n\npara two"
    chunks = split_into_chunks(content)
    # Both paragraphs stay under the size cap, so they're packed into one chunk.
    assert len(chunks) == 1
    assert "para one" in chunks[0][1]
    assert "para two" in chunks[0][1]


def test_large_content_within_one_section_is_split_into_multiple_chunks() -> None:
    long_paragraph = "word " * 200  # well past the 800-char soft cap
    content = f"# Section\n{long_paragraph}\n\n{long_paragraph}\n\n{long_paragraph}"
    chunks = split_into_chunks(content)
    assert len(chunks) > 1
    assert all(section == "Section" for section, _ in chunks)


def test_empty_content_produces_no_chunks() -> None:
    assert split_into_chunks("") == []
    assert split_into_chunks("\n\n\n") == []
