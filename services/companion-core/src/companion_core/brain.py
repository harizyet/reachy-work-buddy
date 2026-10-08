"""Read-only view of the owner's records for the Brain page (Phase 47D, docs/phase-47.md section 7, decision D4).

Everything here is derived from the authoritative stores at request time, through the same source adapters, access rules
and retrieval-time revalidation the knowledge layer uses (docs/phase-44.md D2, D3, D6). It does not read the knowledge
index, so it works with `KNOWLEDGE_INDEXING_ENABLED=false`, and it writes nothing. A later implementation may take its
candidates from the index; it must still pass them through the same checks, and the HTTP contract must not change.

What a caller is allowed to see is decided here from trusted state, never from the request: the owner, on a private
channel, up to work-private (sensitive records are withheld), for local display. A record the owner may not see is simply
absent: it is not in a page, not in a count and not in an edge, and a request for it by id answers exactly like a record
that does not exist.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from companion_core.knowledge.revalidate import _knowledge_item
from companion_core.knowledge.sources import Indexable, SourceAdapter
from companion_core.semantic import access
from companion_core.semantic.model import AccessContext, SourceType
from shared.models.response import Privacy

SOURCE_TYPES: tuple[SourceType, ...] = ("memory", "document", "meeting", "note", "task", "reminder")
DEFAULT_LIMIT = 100
MAX_LIMIT = 200
# A ceiling on how many records one request will examine, whatever the owner has stored.
MAX_SCAN = 5000
EXCERPT_CHARS = 280
TITLE_CHARS = 90
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class BrainNode(BaseModel):
    id: str  # "type:source_id": the owning store's id, stable for the life of the record
    type: SourceType
    title: str
    excerpt: str
    observed_at: datetime | None = None
    source_ref: dict[str, str]
    sensitivity: Privacy
    project_scope: str | None = None


class BrainPage(BaseModel):
    nodes: list[BrainNode]
    next: str | None = None
    truncated: bool = False


class BrainSummary(BaseModel):
    total: int
    by_type: dict[str, int]
    edges: int
    truncated: bool = False


class BrainEdges(BaseModel):
    edges: list[dict] = Field(default_factory=list)
    # Why the list may be empty, in words: no structured link between these record types exists to draw.
    note: str = ""


class InvalidCursor(ValueError):
    pass


def owner_access(principal: str) -> AccessContext:
    """The owner browsing their own records on screen: private channel, work-private ceiling, local processing only."""
    return access.access_for_owner(principal, channel_private=True, allow_sensitive=False, destinations=frozenset({"local"}))


def _clip(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _representative(items: list[Indexable]) -> Indexable:
    """The part that stands for a record: a meeting's summary if it has one, otherwise its first part."""
    for item in items:
        if item.kind in ("meeting_summary",):
            return item
    return items[0]


def _node_for(source_type: SourceType, source_id: str, items: list[Indexable]) -> BrainNode:
    rep = _representative(items)
    # A node carries the most restrictive classification of its parts.
    sensitivity = access.effective_sensitivity(*(i.sensitivity for i in items))
    title = rep.title or _clip(rep.text, TITLE_CHARS)
    return BrainNode(
        id=f"{source_type}:{source_id}", type=source_type, title=_clip(title, TITLE_CHARS) or source_type,
        excerpt=_clip(rep.text, EXCERPT_CHARS), observed_at=rep.observed_at,
        source_ref={"kind": source_type, "id": source_id}, sensitivity=sensitivity, project_scope=rep.project_scope,
    )


async def _visible_node(adapter: SourceAdapter, source_id: str, context: AccessContext) -> BrainNode | None:
    """Revalidate one record now: it must exist, be visible in its store, and every part must pass the access rules. A
    record with any part the caller may not see is withheld whole, so a partly readable record never leaks its remainder."""
    state = await adapter.state(source_id)
    if state.status != "visible" or not state.items:
        return None
    for item in state.items:
        if access.decide(context, _knowledge_item(item, item.sensitivity)) is not None:
            return None
    return _node_for(adapter.source_type, source_id, state.items)


def _sort_key(node: BrainNode) -> tuple[float, str]:
    return (-(node.observed_at or _EPOCH).timestamp(), node.id)


def _matches(node: BrainNode, query: str) -> bool:
    q = query.strip().lower()
    return not q or q in node.title.lower() or q in node.excerpt.lower() or q in node.type


@dataclass
class Scan:
    nodes: list[BrainNode]
    truncated: bool


async def scan(adapters: dict[str, SourceAdapter], context: AccessContext, types: set[str] | None = None, query: str = "") -> Scan:
    """Every record the caller may see, newest first. Read from the stores on every call."""
    nodes: list[BrainNode] = []
    examined = 0
    truncated = False
    for source_type in SOURCE_TYPES:
        if types is not None and source_type not in types:
            continue
        adapter = adapters.get(source_type)
        if adapter is None:
            continue
        for source_id in await adapter.list_ids():
            if examined >= MAX_SCAN:
                truncated = True
                break
            examined += 1
            node = await _visible_node(adapter, source_id, context)
            if node is not None and _matches(node, query):
                nodes.append(node)
    nodes.sort(key=_sort_key)
    return Scan(nodes, truncated)


def encode_cursor(node: BrainNode) -> str:
    raw = json.dumps(list(_sort_key(node))).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[float, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        stamp, key = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return (float(stamp), str(key))
    except (binascii.Error, ValueError, TypeError, json.JSONDecodeError):
        raise InvalidCursor("Invalid cursor") from None


async def list_page(
    adapters: dict[str, SourceAdapter], context: AccessContext, *, types: set[str] | None, query: str, limit: int, cursor: str | None
) -> BrainPage:
    limit = max(1, min(limit, MAX_LIMIT))
    result = await scan(adapters, context, types, query)
    nodes = result.nodes
    if cursor is not None:
        after = decode_cursor(cursor)
        nodes = [n for n in nodes if _sort_key(n) > after]  # keyset: a record deleted between pages cannot shift the next one
    page = nodes[:limit]
    more = len(nodes) > limit
    return BrainPage(nodes=page, next=encode_cursor(page[-1]) if more and page else None, truncated=result.truncated)


async def get_node(adapters: dict[str, SourceAdapter], context: AccessContext, source_type: str, source_id: str) -> BrainNode | None:
    adapter = adapters.get(source_type)
    return None if adapter is None else await _visible_node(adapter, source_id, context)


async def summarise(adapters: dict[str, SourceAdapter], context: AccessContext) -> BrainSummary:
    """Counts are taken from what the caller may see, never from the stores' raw totals."""
    result = await scan(adapters, context)
    by_type = {t: 0 for t in SOURCE_TYPES}
    for n in result.nodes:
        by_type[n.type] += 1
    return BrainSummary(total=len(result.nodes), by_type=by_type, edges=0, truncated=result.truncated)


async def edges_among(ids: list[str]) -> BrainEdges:
    """Explicit links need structured data that joins record types. No such data exists today (a task does not record the
    meeting it came from, a reminder does not record a task), so there is nothing honest to draw. When a store gains such a
    field, its edges are added here and nowhere else."""
    return BrainEdges(
        edges=[],
        note="No structured links between these kinds of record exist yet, so none are drawn. Nothing is inferred.",
    )
