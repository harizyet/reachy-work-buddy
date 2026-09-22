"""Placeholder intent detection for RAG queries — same honesty-about-scope
as memory_intent.py/task_intent.py/calendar_intent.py: prefix matchers, not
real NLU. `format_answer` is what actually satisfies Phase 13's exit
criterion ("Answers identify their supporting document/section/page where
available") — it always names the source document, and the section too
when the retrieved chunk has one.
"""

from __future__ import annotations

from shared.models.rag import RetrievedChunk

_QUERY_PREFIXES = ("search docs for ", "what do the docs say about ", "look up in the docs ", "look up ")


def match_query(text: str) -> str | None:
    lowered = text.strip().lower()
    for prefix in _QUERY_PREFIXES:
        if lowered.startswith(prefix):
            return text.strip()[len(prefix) :].strip() or None
    return None


def format_answer(results: list[RetrievedChunk], query: str) -> str:
    if not results:
        return f"I couldn't find anything in the docs about '{query}'."
    top = results[0]
    provenance = f"'{top.chunk.document_title}'"
    if top.chunk.section:
        provenance += f", section '{top.chunk.section}'"
    return f"From {provenance}: {top.chunk.content}"
