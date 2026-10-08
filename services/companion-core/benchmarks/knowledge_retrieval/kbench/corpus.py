"""Building the corpus into fresh in-memory stores (the real store classes, so a baseline measures real behaviour)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from companion_core.meetings.models import MeetingJobStatus
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore

from kbench.fixtures import load_corpus
from shared.models.memory import MemoryType
from shared.models.response import Privacy

EMBED_DIM = 64


def hashing_embed(texts: list[str]) -> list[list[float]]:
    """A deterministic bag-of-words embedding (md5 buckets). It stands in for the sentence-transformers model so runs are
    reproducible and need no download: document scores in the baseline are therefore lexical, not MiniLM semantic scores."""
    vectors = []
    for text in texts:
        vector = [0.0] * EMBED_DIM
        for word in "".join(ch if ch.isalnum() else " " for ch in text.lower()).split():
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % EMBED_DIM] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        vectors.append([v / norm for v in vector] if norm else vector)
    return vectors


@dataclass
class BuiltCorpus:
    memory: InMemoryMemoryStore
    documents: InMemoryDocumentStore
    meetings: InMemoryMeetingStore
    planner: InMemoryPlannerStore
    tasks: InMemoryTaskStore
    spec: dict[str, Any]
    # logical id <-> store id, per source type; document chunks map by (logical id, chunk index) to a chunk id
    store_id: dict[str, str] = field(default_factory=dict)
    logical: dict[tuple[str, str], str] = field(default_factory=dict)
    chunk_logical: dict[str, tuple[str, int]] = field(default_factory=dict)


async def build_corpus(embed_fn=hashing_embed) -> BuiltCorpus:
    spec = load_corpus()
    built = BuiltCorpus(
        memory=InMemoryMemoryStore(), documents=InMemoryDocumentStore(embed_fn=embed_fn),
        meetings=InMemoryMeetingStore(), planner=InMemoryPlannerStore(), tasks=InMemoryTaskStore(), spec=spec,
    )

    def link(kind: str, logical_id: str, real_id: str) -> None:
        built.store_id[f"{kind}:{logical_id}"] = real_id
        built.logical[(kind, real_id)] = logical_id

    for item in spec["memories"]:
        record = await built.memory.add_memory(
            content=item["text"], source="benchmark", type=MemoryType(item["type"]), project_scope=item["scope"],
            sensitivity=Privacy(item["sensitivity"]),
            expires_at=datetime.fromisoformat(item["expires"]) if item.get("expires") else None,
        )
        record.created_at = datetime.fromisoformat(item["created"])  # the in-memory store hands back its own object
        link("memory", item["id"], record.id)
        if item.get("forgotten"):
            await built.memory.forget(record.id)
    for doc in spec["documents"]:
        chunks = await built.documents.ingest_document(
            title=doc["title"], content=doc["content"], source=doc["source"],
            sensitivity=Privacy(doc["sensitivity"]), project_scope=doc["scope"],
        )
        link("document", doc["id"], chunks[0].document_id)
        for chunk in chunks:
            built.chunk_logical[chunk.id] = (doc["id"], chunk.chunk_index)
    for entry in spec["meetings"]:
        meeting = await built.meetings.create_meeting(
            title=entry["title"], audio=b"x", source_filename="m.wav", content_type="audio/wav",
            project_scope=entry["scope"], sensitivity=Privacy(entry["sensitivity"]),
        )
        built.meetings._touch(  # the established test pattern for seeding a transcript without the worker
            meeting,
            transcript_segments=[{k: v for k, v in s.items() if k != "speaker"} for s in entry["segments"]],
            diarization_segments=[{"start": s["start"], "end": s["end"], "speaker": s["speaker"]} for s in entry["segments"]],
            status=MeetingJobStatus.ALIGNING,
        )
        await built.meetings.set_speaker_names(meeting.id, entry["speaker_names"])
        for index, text in entry["corrections"].items():
            await built.meetings.set_correction(meeting.id, int(index), text)
        link("meeting", entry["id"], meeting.id)
    for note in spec["notes"]:
        record = await built.planner.add_note(
            note["title"], note["body"], sensitivity=Privacy(note["sensitivity"]), project_scope=note["scope"]
        )
        link("note", note["id"], record.id)
    for task in spec["tasks"]:
        record = await built.tasks.add_task(task["text"], sensitivity=Privacy(task["sensitivity"]), project_scope=task["scope"])
        if task["done"]:
            await built.tasks.complete_task(record.id)
        link("task", task["id"], record.id)
    for reminder in spec["reminders"]:
        record = await built.planner.add_reminder(
            reminder["text"], datetime.fromisoformat("2030-01-01T10:00:00+00:00"), sensitivity=Privacy(reminder["sensitivity"])
        )
        link("reminder", reminder["id"], record.id)
    return built


async def fingerprint(built: BuiltCorpus) -> str:
    """A hash of everything a retrieval could change or an injected instruction could be blamed for: the content of every store.
    `last_accessed` is excluded because MemoryStore.recall stamps it by design; that read-side write is reported separately."""
    memories = [
        {**m.model_dump(mode="json"), "last_accessed": None}
        for m in [*await built.memory.list_memories(), *await built.memory.find_forgotten("")]
    ]
    documents = [c.model_dump(mode="json") for c in built.documents._chunks.values()]
    meetings = [m.model_dump(mode="json", exclude={"updated_at"}) for m in await built.meetings.list_meetings()]
    state = {
        "memories": sorted(memories, key=lambda m: m["id"]),
        "documents": sorted(documents, key=lambda c: c["id"]),
        "meetings": sorted(meetings, key=lambda m: m["id"]),
        "notes": sorted((n.model_dump(mode="json") for n in await built.planner.list_notes()), key=lambda n: n["id"]),
        "reminders": sorted((r.model_dump(mode="json") for r in await built.planner.list_reminders()), key=lambda r: r["id"]),
        "receipts": [r.model_dump(mode="json") for r in await built.planner.list_receipts()],
        "tasks": sorted((t.model_dump(mode="json") for t in await built.tasks.list_tasks()), key=lambda t: t["id"]),
    }
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()


async def memory_access_stamps(built: BuiltCorpus) -> int:
    """How many memories have been marked as accessed (a retrieval side effect worth knowing about)."""
    return sum(1 for m in await built.memory.list_memories() if m.last_accessed is not None)
