"""Candidate generation over the knowledge index (Phase 44D): lexical (PostgreSQL full-text) and vector (pgvector cosine) search.

These return *candidates only*: references with a score and the indexed match text. They are not answers and not authorised. The index
can be stale, so nothing here decides what a caller may see; `revalidate` does that against the stores. The filters below narrow the
search for speed and as a second line of defence (an unauthorised row is never even a candidate), but they use the index's own copy of
each label, which can lag the source, so they are never relied on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from psycopg_pool import AsyncConnectionPool

from companion_core.knowledge.index import InMemoryKnowledgeIndex
from companion_core.semantic.model import AccessContext, SourceFilters
from shared.models.response import Privacy

_ORDER = (Privacy.PUBLIC, Privacy.WORK_PRIVATE, Privacy.SENSITIVE)


@dataclass(frozen=True)
class SearchFilter:
    sensitivities: tuple[str, ...] | None = None  # labels at or below the ceiling; None = no access pre-filter
    scopes: tuple[str, ...] | None = None  # None = unrestricted; otherwise these scopes plus unscoped rows
    exclude_local_only: bool = False  # the caller may reach the cloud, so meeting speech must not be a candidate
    source_types: tuple[str, ...] | None = None
    kinds: tuple[str, ...] | None = None
    current_only: bool = True
    pinned: tuple[tuple[str, str], ...] | None = None  # restrict to these (source_type, source_id) pairs


def build_filter(
    access: AccessContext, source_filters: SourceFilters | None, *, temporal: str, prefilter: bool = True, pinned_only: bool = False
) -> SearchFilter:
    f = source_filters or SourceFilters()
    allowed = tuple(p.value for p in _ORDER[: _ORDER.index(access.sensitivity_ceiling) + 1])
    return SearchFilter(
        sensitivities=allowed if prefilter else None,
        scopes=tuple(sorted(access.project_scopes)) if (prefilter and access.project_scopes is not None) else None,
        exclude_local_only=prefilter and bool(access.destinations - {"local", "deep_local"}),
        source_types=tuple(sorted(f.source_types)) if f.source_types else None,
        kinds=tuple(sorted(f.kinds)) if f.kinds else None,
        current_only=temporal == "current",
        pinned=tuple(sorted(f.pinned_sources)) if (pinned_only and f.pinned_sources) else None,
    )


@dataclass(frozen=True)
class SearchHit:
    ref_key: str
    score: float
    match_text: str


class SearchBackend(Protocol):
    async def lexical(self, query: str, flt: SearchFilter, limit: int) -> list[SearchHit]: ...
    async def vector(self, vector: list[float], flt: SearchFilter, limit: int) -> list[SearchHit]: ...


def _where(flt: SearchFilter) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if flt.sensitivities is not None:
        clauses.append("sensitivity = ANY(%s)")
        params.append(list(flt.sensitivities))
    if flt.scopes is not None:
        clauses.append("(project_scope IS NULL OR project_scope = ANY(%s))")
        params.append(list(flt.scopes))
    if flt.exclude_local_only:
        clauses.append("NOT local_only")
    if flt.source_types:
        clauses.append("source_type = ANY(%s)")
        params.append(list(flt.source_types))
    if flt.kinds:
        clauses.append("kind = ANY(%s)")
        params.append(list(flt.kinds))
    if flt.current_only:
        clauses.append("(valid_until IS NULL OR valid_until > now())")
    if flt.pinned:
        clauses.append("(source_type, source_id) IN (" + ", ".join(["(%s, %s)"] * len(flt.pinned)) + ")")
        for source_type, source_id in flt.pinned:
            params += [source_type, source_id]
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


class PostgresSearch:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def lexical(self, query: str, flt: SearchFilter, limit: int) -> list[SearchHit]:
        """Any content word may match (an OR of the stemmed words), ranked by `ts_rank_cd`. `plainto_tsquery` ignores operators in the
        text, so a question cannot inject query syntax; the words are joined with | afterwards."""
        extra, params = _where(flt)
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT plainto_tsquery('english', %s)::text", (query,))
            tsq = (await cur.fetchone())[0]
            if not tsq:
                return []  # nothing but stop words
            cur = await conn.execute(
                "WITH q AS (SELECT to_tsquery('english', %s) AS tsq) "
                "SELECT ref_key, ts_rank_cd(tsv, tsq, 32)::float8, match_text FROM knowledge_items, q "
                f"WHERE tsv @@ tsq{extra} ORDER BY 2 DESC, ref_key LIMIT %s",
                (tsq.replace(" & ", " | "), *params, limit),
            )
            return [SearchHit(r[0], r[1], r[2]) for r in await cur.fetchall()]

    async def vector(self, vector: list[float], flt: SearchFilter, limit: int) -> list[SearchHit]:
        extra, params = _where(flt)
        literal = "[" + ",".join(f"{v:.7g}" for v in vector) + "]"
        async with self._pool.connection() as conn, conn.transaction():
            # With filters, the approximate index can run out of candidates before the filters are satisfied; let it keep scanning.
            await conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            await conn.execute("SET LOCAL hnsw.ef_search = 100")
            cur = await conn.execute(
                "SELECT ref_key, (1 - (embedding <=> %s::vector))::float8, match_text FROM knowledge_items "
                f"WHERE embedding IS NOT NULL{extra} ORDER BY embedding <=> %s::vector, ref_key LIMIT %s",
                (literal, *params, literal, limit),
            )
            return [SearchHit(r[0], r[1], r[2]) for r in await cur.fetchall()]


_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "i", "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "what", "when", "where", "which", "who", "why", "with"])


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


@dataclass
class InMemorySearch:
    """A test double with the same contract over `InMemoryKnowledgeIndex`: lexical = overlap of content words, vector = cosine. It is
    not a model of Postgres ranking; it exists so the pipeline around it (fusion, revalidation, top-up) is testable without a database."""

    index: InMemoryKnowledgeIndex
    calls: list[str] = field(default_factory=list)

    def _rows(self, flt: SearchFilter):
        for row in self.index.rows.values():
            if flt.sensitivities is not None and row.sensitivity.value not in flt.sensitivities:
                continue
            if flt.scopes is not None and row.project_scope is not None and row.project_scope not in flt.scopes:
                continue
            if flt.exclude_local_only and row.local_only:
                continue
            if flt.source_types and row.source_type not in flt.source_types:
                continue
            if flt.kinds and row.kind not in flt.kinds:
                continue
            if flt.pinned and (row.source_type, row.source_id) not in flt.pinned:
                continue
            if flt.current_only and row.valid_until is not None and row.valid_until <= datetime.now(UTC):
                continue
            yield row

    async def lexical(self, query: str, flt: SearchFilter, limit: int) -> list[SearchHit]:
        self.calls.append("lexical")
        wanted = set(_tokens(query))
        scored = [(len(wanted & set(_tokens(r.match_text))), r) for r in self._rows(flt)]
        scored = [(s, r) for s, r in scored if s]
        scored.sort(key=lambda sr: (-sr[0], sr[1].ref_key))
        return [SearchHit(r.ref_key, float(s), r.match_text) for s, r in scored[:limit]]

    async def vector(self, vector: list[float], flt: SearchFilter, limit: int) -> list[SearchHit]:
        self.calls.append("vector")
        scored = []
        for row in self._rows(flt):
            other = self.index.embeddings[row.ref_key]
            dot = sum(a * b for a, b in zip(vector, other, strict=True))
            norm = (sum(a * a for a in vector) ** 0.5) * (sum(b * b for b in other) ** 0.5)
            scored.append((dot / norm if norm else 0.0, row))
        scored.sort(key=lambda sr: (-sr[0], sr[1].ref_key))
        return [SearchHit(r.ref_key, s, r.match_text) for s, r in scored[:limit]]
