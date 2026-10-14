"""Synthetic fixtures for the Phase 53 tests (docs/phase-53.md section 12): decks and transcripts with known answers, a fake document library over the REAL DocumentService rules (access,
deletion states, store) and a scripted local model. Importable by the test modules through pytest's importlib mode via `conftest`-free path insertion (see the test files)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from companion_core.document_library.models import (
    Document,
    DocumentError,
    DocumentState,
)
from companion_core.document_library.qa import Evidence, Passage, keywords
from companion_core.document_library.service import DocumentService
from companion_core.document_library.store import (
    InMemoryDocumentStore as InMemoryLibraryStore,
)
from companion_core.meeting_multimodal.service import MeetingMultimodalService
from companion_core.meeting_multimodal.store import InMemoryMultimodalStore
from companion_core.meetings.models import Meeting, MeetingJobStatus
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.tasks.store import InMemoryTaskStore

from shared.models.document_library import DocumentContentOut
from shared.models.response import Privacy

STARTED = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)

DECK_A = ("Edge Platform Review", [
    "# Edge Platform Review\nQuarterly architecture review for the platform group.",
    "# Edge Architecture\nInference runs on the Jetson edge node. The control plane is separate from inference. Latency target is 200 ms at the edge.",
    "# Telemetry Pipeline\nTelemetry ingestion uses Kafka streaming with seven day retention and compaction.",
    "# Cost Model\nGPU spend per month, hardware procurement, budget forecast and depreciation schedule.",
    "# Security Posture\nCertificate rotation, mutual TLS between services, secrets vault and audit logging.",
    "# Roadmap\nQ4 milestones: firmware rollout and pilot sites.",
])
DECK_B = ("Edge Platform Review Draft", [
    "# Edge Platform Review Draft\nAn earlier draft of the deck.",
    "# Edge Architecture\nInference runs on the Raspberry edge node. The control plane is separate from inference. Latency target is 500 ms.",
    "# Cost Model\nGPU spend per month and budget forecast.",
])

ARCH = ["Now the architecture: inference runs on the Jetson edge node,", "and the control plane is kept separate from inference on purpose.", "That separation is the key point of the edge architecture for us."]
TELEMETRY = ["Telemetry ingestion goes through Kafka streaming,", "we keep seven days of retention with compaction on the topics,", "so the pipeline can replay events after an outage."]
COST = ["The budget forecast is the worry: GPU spend per month keeps rising,", "and hardware procurement needs sign-off before the depreciation schedule changes.", "We must flag that to finance this week."]
SMALL_TALK = ["How was everyone's weekend, did you get out of the city at all?", "I went hiking near the lake, the weather was lovely for it.", "Anyway, shall we get started with the agenda for today?"]
SECURITY = ["Certificate rotation is overdue, and mutual TLS between services is not enforced yet,", "so the secrets vault and the audit logging both need an owner.", "Agreed, Priya will own certificate rotation by Friday."]


def make_meeting(groups: list[list[str]], *, gap: float = 12.0, **over) -> Meeting:
    """Each group is one topic: its segments are a second apart, groups are `gap` seconds apart (more than the window builder's longest tolerated pause)."""
    segments, aligned = [], []
    clock = 0.0
    for g in groups:
        for n, text in enumerate(g):
            speaker = "SPEAKER_00" if n % 2 == 0 else "SPEAKER_01"  # the speaker changes inside one topic
            seg = {"start": clock, "end": clock + 8.0, "text": text}
            segments.append(seg)
            aligned.append({**seg, "speaker": speaker})
            clock += 9.0
        clock += gap
    base = {"title": "Edge platform review", "source_filename": "a.wav", "content_type": "audio/wav", "audio_path": "/nonexistent", "started_at": STARTED, "transcript_segments": segments,
            "aligned_segments": aligned, "diarization_segments": [], "status": MeetingJobStatus.COMPLETE, "audio_gaps": None}
    base.update(over)
    return Meeting(**base)


class FakeStores:
    def __init__(self) -> None:
        self.removed: list[str] = []

    async def delete(self, source_hash: str) -> None:
        self.removed.append(source_hash)


class FakeLibrary(DocumentService):
    """The real DocumentService rules (the store, the access check, the deleting state, the deletion listeners) over fixed page text instead of the worker."""

    def __init__(self) -> None:
        super().__init__(InMemoryLibraryStore(), FakeStores(), None)
        self.pages: dict[str, list[str]] = {}
        self.reads = 0

    async def add(self, title: str, pages: list[str], *, sensitivity: Privacy = Privacy.WORK_PRIVATE, project_scope: str | None = None, state: DocumentState = DocumentState.READY) -> Document:
        doc = Document(title=title, filename=f"{title}.pdf", mime_type="application/pdf", source_hash=f"{abs(hash(title)):x}".ljust(64, "0")[:64], size_bytes=100, state=state, backend_ref=None,
                       backend_revision="r1", tier="basic", page_count=len(pages), sensitivity=sensitivity, project_scope=project_scope)
        await self.store.add(doc)
        self.pages[doc.id] = pages
        return doc

    async def require_usable(self, document_id: str) -> Document:
        document = await self.get(document_id)
        if document.state is DocumentState.DELETING:
            raise DocumentError(404, "No such document")
        return document

    async def read(self, document_id, access, *, page_range=None, after=None, limit=8000):
        document = await self.require_usable(document_id)
        self.authorize(document, access)
        self.reads += 1
        number = int(page_range)
        if not 1 <= number <= len(self.pages[document_id]):
            raise DocumentError(404, "No such location in the document")
        return DocumentContentOut(document_id=document.id, title=document.title, source_hash=document.source_hash, evidence_type="derived_extraction", tier="basic",
                                  content=f"<!-- page {number} of {len(self.pages[document_id])} -->\n{self.pages[document_id][number - 1]}")

    async def evidence_for_question(self, document_id, access, question):
        document = await self.require_usable(document_id)
        self.authorize(document, access)
        words = set(keywords(question))
        scored = []
        for number, text in enumerate(self.pages[document_id], start=1):
            hit = len(words & {w.strip(".,:;").lower() for w in text.split()})
            if hit:
                scored.append((hit, number, text))
        top = sorted(scored, key=lambda x: (-x[0], x[1]))[:3]
        return Evidence(document=document, passages=[Passage(page=n, text=" ".join(t.split())) for _, n, t in sorted(top, key=lambda x: x[1])])


_CANDIDATE = re.compile(r"^C(\d) \(from “(.*?)”\)(?: “(.*?)”)?: ", re.MULTILINE)


class Model:
    """A scripted local model. `choices` is a list of rules (discussion needle, deck title, page title) for the page choice: the first rule whose needle is in the discussion picks the candidate
    with that page title (and deck title, when given); no rule means 'none of them'. `analysis` and `answer` are callables over the prompt text. Every call is recorded."""

    def __init__(self, choices=(), *, analysis=None, answer=None, reason: str = "The wording matches the slide.", contradiction=None, fail=None) -> None:
        self.choices, self.analysis, self.answer, self.reason, self.contradiction, self.fail = list(choices), analysis, answer, reason, contradiction, fail
        self.calls: list[tuple[str, str]] = []

    @property
    def kinds(self) -> list[str]:
        return [k for k, _ in self.calls]

    async def provider(self):
        async def ask(messages, max_tokens):
            system, user = messages[0]["content"], messages[1]["content"]
            if self.fail:
                raise self.fail
            if system.startswith("You decide which one"):
                self.calls.append(("choose", user))
                return self._choose(user)
            if system.startswith("You read part of ONE meeting transcript together"):
                self.calls.append(("analysis", user))
                return json.dumps({"items": self.analysis(user) if self.analysis else []})
            if system.startswith("You answer ONE question"):
                self.calls.append(("answer", user))
                return json.dumps({"parts": self.answer(user)}) if self.answer else json.dumps({"parts": [{"kind": "unknown", "text": "The excerpts do not settle this.", "cites": []}]})
            raise AssertionError("unexpected prompt")

        return ask, "scripted-7b"

    def _choose(self, user: str) -> str:
        discussion = user.split("<<<DISCUSSION>>>")[1].split("<<<END DISCUSSION>>>")[0].lower()
        candidates = {int(n): (deck, title or "") for n, deck, title in _CANDIDATE.findall(user)}
        for needle, deck, title in self.choices:
            if needle.lower() in discussion:
                for n, (d, t) in candidates.items():
                    if t == title and (deck is None or d == deck):
                        out = {"choice": n, "alternatives": [], "reason": self.reason, "contradiction": None}
                        if self.contradiction and self.contradiction[0] == needle:
                            out["contradiction"] = {"candidate": n, **self.contradiction[1]}
                        return json.dumps(out)
        return json.dumps({"choice": 0, "alternatives": [], "reason": "", "contradiction": None})


def blocks(user: str) -> dict[str, str]:
    """The labelled excerpts of an answer prompt: {"T1": text, "D1": text}."""
    out = {}
    for match in re.finditer(r"^\[([TD]\d+)\][^\n]*:\n(.*?)(?=\n\n\[[TD]\d+\]|\Z)", user, re.MULTILINE | re.DOTALL):
        out[match.group(1)] = match.group(2)
    return out


class World:
    def __init__(self, groups, *, decks=(DECK_A,), model=None, sensitivity=Privacy.WORK_PRIVATE, deck_sensitivity=None, meeting_scope=None, deck_scope=None, **meeting_over) -> None:
        self.groups, self.deck_specs = groups, decks
        self.lib, self.meetings, self.tasks, self.planner, self.store = FakeLibrary(), InMemoryMeetingStore(), InMemoryTaskStore(), InMemoryPlannerStore(), InMemoryMultimodalStore()
        self.model = model or Model()
        self.meeting = make_meeting(groups, sensitivity=sensitivity, project_scope=meeting_scope, **meeting_over)
        self.deck_sensitivity, self.deck_scope = deck_sensitivity or Privacy.WORK_PRIVATE, deck_scope
        self.docs: list[Document] = []
        self.svc = MeetingMultimodalService(self.store, self.meetings, self.lib, self.tasks, self.planner, provider=self.model.provider)
        self.lib.deletion_listeners.append(self.svc.document_deleted)

    async def setup(self) -> World:
        self.meetings._meetings[self.meeting.id] = self.meeting
        for title, pages in self.deck_specs:
            self.docs.append(await self.lib.add(title, pages, sensitivity=self.deck_sensitivity, project_scope=self.deck_scope))
        return self

    @property
    def mid(self) -> str:
        return self.meeting.id

    async def link_all(self, access):
        for d in self.docs:
            await self.svc.link(self.mid, d.id, access)

    async def aligned(self, access, *, force=False):
        await self.link_all(access)
        await self.svc.enqueue_alignment(self.mid, access, force=force)
        assert await self.svc.process_next()
        return await self.svc.overview(self.mid, access)


def by_start(view: dict, start: float) -> dict:
    return next(w for w in view["windows"] if w["start"] == start)
