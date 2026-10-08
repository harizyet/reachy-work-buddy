"""The interface a retrieval system implements to be benchmarked, and the two Phase 43 baselines.

An adapter is handed freshly built stores and a case, and returns ranked hits. It must not modify the stores (the harness
fingerprints them before and after every case) and it receives the case's access profile so a system that enforces access can
use it; the baselines ignore it, which is exactly what the leakage metric measures. Hits carry logical reference keys
("type:id[#locator]"), never store ids, so a system with its own ids is scored on what it found, not how it names it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from companion_core.meetings.outputs import _words, relevant_lines, transcript_lines

from kbench.corpus import BuiltCorpus


@dataclass(frozen=True)
class Hit:
    key: str  # "type:id[#locator]" in the fixtures' logical ids
    text: str
    score: float | None = None


@dataclass(frozen=True)
class Retrieval:
    """What a system with an internal filtering stage returns. `exposed` is what it would hand to the caller or the model and
    is the only thing the security gate judges. `candidates` is everything it considered before filtering; a candidate that a
    filter rejected is a diagnostic about retrieval, not a disclosure. A system without a filtering stage (the B0 baselines)
    returns a plain list, which is treated as exposed and reports no candidates."""

    exposed: list[Hit]
    candidates: list[Hit]


class RetrievalAdapter(Protocol):
    name: str
    description: str

    async def load(self, built: BuiltCorpus) -> None:
        """Prepare the system over the built stores (build an index, open connections). Called once per run."""

    async def retrieve(self, case: dict[str, Any], profile: dict[str, Any]) -> list[Hit] | Retrieval:
        """Ranked hits for the case's question, best first; or a Retrieval to also report the unfiltered candidates."""


class _Base:
    built: BuiltCorpus

    async def load(self, built: BuiltCorpus) -> None:
        self.built = built

    def _doc_hits(self, results) -> list[Hit]:
        hits = []
        for result in results:
            doc, index = self.built.chunk_logical[result.chunk.id]
            hits.append(Hit(f"document:{doc}#{index}", result.chunk.content, result.score))
        return hits

    def _memory_hits(self, records) -> list[Hit]:
        return [Hit(f"memory:{self.built.logical[('memory', r.id)]}", r.content) for r in records]

    async def _meeting_hits(self, case_question: str, logical_id: str) -> list[Hit]:
        """Phase 43 as shipped: the whole transcript when it fits the context, otherwise the lines sharing words with the
        question plus a neighbour on each side, in meeting order (companion_core.meetings.outputs.relevant_lines)."""
        meeting = await self.built.meetings.get_meeting(self.built.store_id[f"meeting:{logical_id}"])
        lines = transcript_lines(meeting)
        positions: dict[str, list[int]] = {}
        for index, line in enumerate(lines):
            positions.setdefault(line, []).append(index)
        hits = []
        for line in relevant_lines(lines, case_question):
            hits.append(Hit(f"meeting:{logical_id}#{positions[line].pop(0)}", line))
        return hits


class B0Shipped(_Base):
    name = "b0"
    description = (
        "Today's lookups, each called with the question as its query: MemoryStore.recall (a substring match on the whole "
        "question), DocumentStore.search (top 3) and, only for a case with an attached meeting, Phase 43 relevant_lines. "
        "Notes, tasks and reminders have no free-form lookup today, and an unattached meeting is not searched. "
        "Source order is fixed (documents, memories, meeting); within a source, the store's own order."
    )

    async def retrieve(self, case: dict[str, Any], profile: dict[str, Any]) -> list[Hit]:
        question = case["question"]
        hits = self._doc_hits(await self.built.documents.search(question, top_k=3))
        hits += self._memory_hits(await self.built.memory.recall(question))
        if case.get("attached_meeting"):
            hits += await self._meeting_hits(question, case["attached_meeting"])
        return hits


class B0Oracle(_Base):
    name = "b0-oracle"
    description = (
        "A ceiling for today's mechanisms, not shipped behaviour: the same store lookups called once per content word of "
        "the question, every source searched, and every meeting treated as attached. Hits sharing no word with the question "
        "are dropped and the rest are ranked by word overlap (the measure Phase 43 uses), ties in source order."
    )

    async def retrieve(self, case: dict[str, Any], profile: dict[str, Any]) -> list[Hit]:
        question = case["question"]
        words = sorted(_words(question))
        pool: list[Hit] = []
        pool += self._doc_hits(await self.built.documents.search(question, top_k=50))
        seen: set[str] = set()
        for word in words:
            for record in await self.built.memory.recall(word):
                if record.id not in seen:
                    seen.add(record.id)
                    pool += self._memory_hits([record])
        for word in words:
            for note in await self.built.planner.list_notes(word):
                key = f"note:{self.built.logical[('note', note.id)]}"
                if all(h.key != key for h in pool):
                    pool.append(Hit(key, f"{note.title}\n{note.body}"))
            for task in await self.built.tasks.search_tasks(word):
                key = f"task:{self.built.logical[('task', task.id)]}"
                if all(h.key != key for h in pool):
                    pool.append(Hit(key, task.text))
        for reminder in await self.built.planner.list_reminders():
            if _words(reminder.text) & set(words):
                pool.append(Hit(f"reminder:{self.built.logical[('reminder', reminder.id)]}", reminder.text))
        for entry in self.built.spec["meetings"]:
            pool += await self._meeting_hits(question, entry["id"])
        wanted = set(words)
        scored = [(len(wanted & _words(h.text)), order, h) for order, h in enumerate(pool)]
        ranked = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1]))
        return [Hit(h.key, h.text, float(overlap)) for overlap, _, h in ranked]


ADAPTERS: dict[str, Any] = {B0Shipped.name: B0Shipped, B0Oracle.name: B0Oracle}


def _b1(name: str):
    def factory():
        from kbench.b1 import (
            B1Adapter,  # imported on use: it needs PostgreSQL and the knowledge package
        )

        return B1Adapter(name)

    return factory


for _name in ("b1a", "b1b", "b1c", "b1a-nofilter", "b1b-nofilter"):
    ADAPTERS[_name] = _b1(_name)
