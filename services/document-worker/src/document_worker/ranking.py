"""In-document page ranking (Phase 50, found necessary at the first real-model run). MinerU's own search returns ONE snippet per document across the whole library, so it cannot tell which pages of a
document answer a question, and its snippet windows do not line up with page text. This ranks the pages of ONE document from the page text MinerU already parsed: deterministic, bounded by the page
limit, no index and no storage beyond a small in-memory page cache. A hit's page is the page that was scored, so a page number is never inferred from a snippet."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
_STOPWORDS = frozenset(
    ["a", "an", "the", "of", "in", "on", "at", "to", "for", "from", "by", "with", "about", "and", "or", "but", "if", "is", "are", "was", "were", "be", "been", "being", "do", "does", "did", "what", "which", "who", "whom", "whose", "when", "where", "why", "how", "this", "that", "these", "those", "it", "its", "i", "you", "we", "they", "he", "she", "them", "there", "here", "as", "into", "than", "then", "so", "such", "can", "could", "should", "would", "will", "shall", "may", "might", "must", "not", "no", "yes", "tell", "me", "my", "our", "your", "please", "give", "show", "list", "find", "explain", "document", "file", "pdf", "page", "pages", "says", "say", "said", "mention", "mentioned", "according"]
)
SNIPPET_CHARS = 260
MIN_RELATIVE_SCORE = 0.3  # a page scoring under this share of the best page is noise, not an answer


def stem(word: str) -> str:
    """A light stemmer: enough for logs/log, retained/retain, requirements/requirement. Not a language model."""
    word = word.lower()
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def terms(query: str) -> list[str]:
    seen: list[str] = []
    for token in _TOKEN.findall(query.lower()):
        if len(token) > 1 and token not in _STOPWORDS:
            stemmed = stem(token)
            if stemmed not in seen:
                seen.append(stemmed)
    return seen


@dataclass(frozen=True)
class Ranked:
    page: int
    score: float
    snippet: str


def _counts(text: str, wanted: list[str]) -> dict[str, int]:
    found = dict.fromkeys(wanted, 0)
    for token in _TOKEN.findall(text.lower()):
        stemmed = stem(token)
        if stemmed in found:
            found[stemmed] += 1
    return found


def _snippet(text: str, wanted: list[str]) -> str:
    """A window of the page around the first occurrence of the rarest-looking query term, cut at word boundaries."""
    lower = text.lower()
    position = min((m.start() for m in _TOKEN.finditer(lower) if stem(m.group()) in wanted), default=0)
    start = max(0, position - SNIPPET_CHARS // 3)
    window = text[start : start + SNIPPET_CHARS]
    if start > 0:
        window = window[window.find(" ") + 1 :] if " " in window else window
    if start + SNIPPET_CHARS < len(text):
        window = window[: window.rfind(" ")] if " " in window else window
    return ("…" if start > 0 else "") + window.strip() + ("…" if start + SNIPPET_CHARS < len(text) else "")


def rank(pages: list[tuple[int, str]], query: str, limit: int) -> list[Ranked]:
    """Pages of one document by how well they match the query (TF-IDF over the document's own pages), best first, at most `limit`."""
    wanted = terms(query)
    if not wanted or not pages:
        return []
    per_page = {number: _counts(text, wanted) for number, text in pages}
    total = len(pages)
    document_frequency = {t: sum(1 for c in per_page.values() if c[t]) for t in wanted}
    scored = []
    for number, text in pages:
        counts = per_page[number]
        score = sum((1 + math.log(counts[t])) * math.log(1 + total / (1 + document_frequency[t])) for t in wanted if counts[t])
        if score > 0:
            scored.append((score, number, text))
    if not scored:
        return []
    scored.sort(key=lambda item: (-item[0], item[1]))
    best = scored[0][0]
    return [Ranked(number, score, _snippet(text, wanted)) for score, number, text in scored if score >= best * MIN_RELATIVE_SCORE][:limit]
