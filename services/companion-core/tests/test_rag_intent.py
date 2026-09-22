from companion_core.rag_intent import format_answer, match_query

from shared.models.rag import DocumentChunk, RetrievedChunk


def _chunk(content: str, section: str | None = None, title: str = "Onboarding Guide") -> DocumentChunk:
    return DocumentChunk(
        id="1", document_id="d1", document_title=title, section=section, content=content, source="doc.md",
        chunk_index=0,
    )


def test_match_query_prefixes() -> None:
    assert match_query("search docs for vacation policy") == "vacation policy"
    assert match_query("what do the docs say about expenses") == "expenses"
    assert match_query("look up in the docs onboarding") == "onboarding"
    assert match_query("look up parking") == "parking"


def test_match_query_returns_none_for_unrelated_text() -> None:
    assert match_query("what's next") is None
    assert match_query("look up") is None  # nothing after the prefix


def test_format_answer_with_no_results() -> None:
    assert format_answer([], "parking") == "I couldn't find anything in the docs about 'parking'."


def test_format_answer_names_the_document_and_section() -> None:
    chunk = _chunk("submit a request in Workday", section="Requesting time off")
    reply = format_answer([RetrievedChunk(chunk=chunk, score=0.9)], "time off")
    assert "Onboarding Guide" in reply
    assert "Requesting time off" in reply
    assert "submit a request in Workday" in reply


def test_format_answer_omits_section_when_absent() -> None:
    chunk = _chunk("some content", section=None)
    reply = format_answer([RetrievedChunk(chunk=chunk, score=0.9)], "query")
    assert "Onboarding Guide" in reply
    assert "section" not in reply
