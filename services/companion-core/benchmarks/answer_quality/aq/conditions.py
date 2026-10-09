"""What the model is given under each condition. Everything else about a request (persona, action boundary, date, question, model,
settings) is identical across conditions, so only the context differs.

  none        no retrieval
  p43         the shipped Phase 43 behaviour: an attached meeting's context as a system message, nothing otherwise
  b1a, b1b    retrieval (lexical; lexical + vector) -> revalidation -> the 44E context builder
  oracle      the case's gold sources only, through the same builder (the upper bound that separates retrieval from generation)
  distractor  authorised but irrelevant sources only, through the same builder (abstention cases): does the model abstain or invent?
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from companion_core.app import ACTION_BOUNDARY_INSTRUCTION, SPOKEN_REPLY_INSTRUCTION
from companion_core.knowledge.context import (
    RenderedContext,
    build_context,
    place_evidence,
)
from companion_core.knowledge.retrieval import Retriever
from companion_core.knowledge.revalidate import _knowledge_item
from companion_core.knowledge.routing import (
    choose_path,
    classify,
    restricted_reply,
    route_status,
)
from companion_core.meetings import outputs as meeting_outputs
from companion_core.persona.context import context_message
from companion_core.semantic.model import SourceFilters
from kbench.fixtures import meeting_object, parse_ref, source_meta
from kbench.security import access_context, violations

from shared.models.persona import PersonaConfig

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
CONDITIONS = ("none", "p43", "b1a", "b1b", "oracle", "distractor")
EXTRA_CONDITIONS = ("b1a_nopre", "b1b_nopre")  # exclusion tests, run on request


@dataclass
class Prepared:
    messages: list[dict[str, str]]
    entries: list[dict[str, Any]] = field(default_factory=list)  # logical refs per cited id
    text: str = ""  # everything retrieved that the model sees
    has_ids: bool = False
    rendered: RenderedContext | None = None
    retrieval_ms: float = 0.0
    build_ms: float = 0.0
    candidates: int = 0
    dropped: dict[str, int] = field(default_factory=dict)
    retrieval_dropped: dict[str, int] = field(default_factory=dict)  # what revalidation refused before the builder saw the bundle
    prompt_violations: list[str] = field(default_factory=list)
    skipped: str | None = None
    fixed_reply: str | None = None  # a deterministic reply that bypasses the model (restricted channel)


def base_messages(case: dict[str, Any]) -> list[dict[str, str]]:
    persona = PersonaConfig()
    msgs = [{"role": "system", "content": persona.system_prompt}, {"role": "system", "content": ACTION_BOUNDARY_INSTRUCTION},
            context_message(persona, NOW)]
    if case["modality"] == "voice":
        msgs.append({"role": "system", "content": SPOKEN_REPLY_INSTRUCTION})
    return msgs + [{"role": "user", "content": case["question"]}]


class Conditions:
    def __init__(self, env, built_spec, llm, *, budget: int, minilm_embed=None, flag_instructions: bool = True) -> None:
        self.env, self.spec, self.llm, self.budget = env, built_spec, llm, budget
        self.flag_instructions = flag_instructions
        self.header, self.note, self.conflicts, self.template = "v1", None, False, False
        self.meta = source_meta(built_spec)
        self.retrievers: dict[str, Retriever] = {}
        self.embed = minilm_embed

    def retriever(self, name: str) -> Retriever:
        from dataclasses import replace

        from companion_core.knowledge.retrieval import B1A, B1B

        if name not in self.retrievers:
            base = {"b1a": B1A, "b1b": B1B}[name.removesuffix("_nopre")]
            # "_nopre": the index pre-filter is off, so revalidation alone has to keep unauthorised rows out (the exclusion test)
            cfg = replace(base, name=name, prefilter=False) if name.endswith("_nopre") else base
            self.retrievers[name] = Retriever(search=self.env.search, adapters=self.env.adapters, config=cfg, embed_fn=self.embed, clock=lambda: NOW)
        return self.retrievers[name]

    def _finish(self, case, prepared: Prepared, items, access, *, pinned=frozenset(), candidates: int | None = None) -> Prepared:
        t = time.perf_counter()
        destination = "cloud" if "cloud" in access.destinations else "local"
        rendered = build_context(
            items, access, destination=destination, budget_tokens=self.budget, count_tokens=self.llm.count_tokens, now=NOW,
            include_historical=case["temporal"] == "include_historical", pinned=pinned, modality=case["modality"],
            candidate_count=candidates, flag_instructions=self.flag_instructions, header_version=self.header, note=self.note, flag_conflicts=self.conflicts,
        )
        prepared.build_ms = (time.perf_counter() - t) * 1000
        prepared.rendered = rendered
        prepared.messages = place_evidence(base_messages(case), rendered)
        prepared.has_ids = True
        prepared.text = rendered.text
        prepared.entries = [{"eid": e.eid, "refs": [self.env.logical_key(k) for k in e.ref_keys]} for e in rendered.entries]
        prepared.dropped = rendered.dropped_counts()
        profile = self.spec["access_profiles"][case["access"]]
        for e in prepared.entries:
            for ref in e["refs"]:
                prepared.prompt_violations += [f"{ref}:{v}" for v in violations(ref, self.meta, profile)]
        return prepared

    async def _items(self, refs: list[str]):
        out = []
        seen: set[str] = set()
        for ref in refs:
            st, sid, loc = parse_ref(ref)
            real = self.env.store_id[f"{st}:{sid}"]
            state = await self.env.adapters[st].state(real)
            for item in state.items:
                logical = self.env.logical_key(item.ref.key)
                if logical in seen:
                    continue
                if loc is None or logical == ref:
                    seen.add(logical)
                    out.append(_knowledge_item(item, item.sensitivity))
        return out

    async def prepare(self, name: str, case: dict[str, Any]) -> Prepared:
        """`name` is a base condition plus optional modifiers: `+routed` (attached meeting keeps Phase 43, status questions read the stores),
        `+v2` (the claim/conflict header), `+cf` (hint when two items give different numbers)."""
        base, *mods = name.split("+")
        self.header = "v2" if "v2" in mods else "v1"
        self.conflicts = "cf" in mods
        self.template = "tmpl" in mods
        if "routed" in mods:
            path = choose_path(case["question"], attached_meeting=bool(case["attached_meeting"]))
            if path == "phase43":
                return await self.prepare("p43", case)
            if path == "status":
                return await self._status(case)
        return await self._prepare_base(base, case)

    async def _status(self, case: dict[str, Any]) -> Prepared:
        profile = self.spec["access_profiles"][case["access"]]
        access = access_context(profile)
        prepared = Prepared(messages=base_messages(case))
        planner, tasks = self.env.stores[1], self.env.stores[2]
        if self.template and restricted_reply(access) is not None and classify(case["question"]) is not None:
            prepared.fixed_reply = restricted_reply(access)
            return prepared
        t = time.perf_counter()
        routed = await route_status(case["question"], access, tasks=tasks, planner=planner, now=NOW, memory=self.env.stores[0])
        prepared.retrieval_ms = (time.perf_counter() - t) * 1000
        prepared.retrieval_dropped = dict(routed.dropped)
        prepared.candidates = routed.total
        self.note = routed.note
        try:
            return self._finish(case, prepared, list(routed.items), access, candidates=routed.total)
        finally:
            self.note = None

    async def _prepare_base(self, name: str, case: dict[str, Any]) -> Prepared:
        profile = self.spec["access_profiles"][case["access"]]
        access = access_context(profile)
        prepared = Prepared(messages=base_messages(case))
        if name == "none":
            return prepared
        if name == "p43":
            if case["attached_meeting"]:
                entry = next(m for m in self.spec["meetings"] if m["id"] == case["attached_meeting"])
                text = meeting_outputs.build_context(meeting_object(entry), case["question"])
                msgs = base_messages(case)
                msgs.insert(len(msgs) - 1, {"role": "system", "content": text})
                prepared.messages, prepared.text = msgs, text
                prepared.entries = []
                prepared.has_ids = False
            return prepared
        if name in ("b1a", "b1b", "b1a_nopre", "b1b_nopre"):
            pinned = None
            if case["attached_meeting"]:
                pinned = SourceFilters(pinned_sources=frozenset({("meeting", self.env.store_id[f"meeting:{case['attached_meeting']}"])}))
            t = time.perf_counter()
            result = await self.retriever(name).retrieve(case["question"], access, pinned, temporal=case["temporal"], limit=10)
            prepared.retrieval_ms = (time.perf_counter() - t) * 1000
            prepared.candidates = len(result.trace.candidates)
            prepared.retrieval_dropped = dict(result.bundle.dropped)
            pins = pinned.pinned_sources if pinned else frozenset()
            return self._finish(case, prepared, list(result.bundle.items), access, pinned=frozenset(pins), candidates=len(result.bundle.items))
        if name == "oracle":
            return self._finish(case, prepared, await self._items(case["gold_refs"]), access)
        if name == "distractor":
            if not case["abstain"] or not case["distractor_refs"]:
                prepared.skipped = "distractor-only runs on abstention cases that list distractors"
                return prepared
            return self._finish(case, prepared, await self._items(case["distractor_refs"]), access)
        raise ValueError(name)
