"""Harness conditions for the groundedness milestone, as a subclass of the frozen `Conditions`. Modifiers (each independently switchable):
  +c1o  C1 re-rank only          +c1f  C1 filter           +c2n  C2 note           +c2t  C2 deterministic reply for UNESTABLISHED
  +c3   C3 attendee routing      +c4   atomic-claim JSON generation (run_g.py)      +c5  C5 validation of the claims (needs +c4)
C1/C2 read a 30-candidate B1a retrieval; every arm shows at most 10 records to the model, so the evidence budget is not the variable."""
from __future__ import annotations

import html
import re
from datetime import UTC, datetime

from companion_core.knowledge.context import _is_historical
from companion_core.knowledge.grounding import (
    answerability,
    propositions,
    routes,
    validate,
)
from companion_core.knowledge.sufficiency import pieces_from_items
from companion_core.semantic import access as rules
from kbench.security import access_context

from aq.conditions import Conditions, Prepared, base_messages
from aq.scoring_v2 import entry_texts

G_MODS = {"c1o", "c1f", "c2n", "c2t", "c3", "c4", "c5"}
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
_INFO = re.compile(r'<evidence id="(E\d+)" info="(.*?)">', re.DOTALL)


class GConditions(Conditions):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.people: list[str] = []
        self.g: set = set()
        self.last_items: list = []

    async def prepare(self, name, case):
        base, *mods = name.split("+")
        self.g = {m for m in mods if m in G_MODS}
        rest = [m for m in mods if m not in G_MODS]
        plain = "+".join([base, *rest])
        if base == "b1a" and (self.g & {"c1o", "c1f", "c2n", "c2t", "c3"}):
            prep = await self._prepare_g(case)
        else:
            prep = await super().prepare(plain, case)
            prep.g = {}
        prep.g_mods = sorted(self.g)
        prep.evidence = self._evidence(prep, case) if prep.rendered is not None else {}
        return prep

    def _finish(self, case, prepared, items, access, **kw):
        self.last_items = list(items)
        return super()._finish(case, prepared, items, access, **kw)

    async def _prepare_g(self, case) -> Prepared:
        profile = self.spec["access_profiles"][case["access"]]
        access = access_context(profile)
        prepared = Prepared(messages=base_messages(case))
        pinned = None
        res = await self.retriever("b1a").retrieve(case["question"], access, pinned, temporal=case["temporal"], limit=30)
        candidates = list(res.bundle.items)
        prepared.retrieval_dropped = dict(res.bundle.dropped)
        skip = {i for i, it in enumerate(candidates) if case["temporal"] != "include_historical" and _is_historical(it, NOW)}
        sel = propositions.select(case["question"], pieces_from_items(candidates), known_people=self.people, skip=skip)
        ans = answerability.assess(sel)
        if "c1f" in self.g:
            shown = propositions.reorder(candidates, sel, "filter", limit=10)
        elif "c1o" in self.g:
            shown = propositions.reorder(candidates, sel, "order", limit=10)
        else:
            shown = candidates[:10]
        info = {"state": ans.state, "reason": ans.reason, "selected": len(sel.selected), "shown": len(shown), "candidates": len(candidates), "relation": sel.propositions[0].relation}
        if "c3" in self.g:
            meetings = [m for m in self.spec["meetings"] if rules.within_ceiling(__import__("shared.models.response", fromlist=["Privacy"]).Privacy(m["sensitivity"]), access.sensitivity_ceiling)]
            routed = routes.route_attendees(case["question"], meetings)
            if routed is not None:
                prepared.fixed_reply = routed.text
                info["routed"] = True
                prepared.g = info
                return prepared
        if "c2t" in self.g and ans.state == answerability.UNESTABLISHED:
            prepared.fixed_reply = answerability.template_reply(ans)
            info["template"] = True
            prepared.g = info
            return prepared
        self.note = answerability.note(ans) if "c2n" in self.g else None
        try:
            prepared = self._finish(case, prepared, shown, access, candidates=len(shown))
        finally:
            self.note = None
        prepared.g = info
        return prepared

    def _evidence(self, prep: Prepared, case) -> dict:
        """The turn's evidence manifest as C5 sees it, built by code: text from the rendered blocks (unescaped), refs and context from the manifest, authorization recomputed from the items and the access rules."""
        access = access_context(self.spec["access_profiles"][case["access"]])
        by_key = {i.ref.key: i for i in self.last_items}
        texts = entry_texts(prep.text)
        infos = dict(_INFO.findall(prep.text))
        out = {}
        for e in prep.rendered.entries:
            items = [by_key.get(k) for k in e.ref_keys]
            ok = bool(items) and all(it is not None and rules.within_ceiling(it.sensitivity, access.sensitivity_ceiling) and rules.scope_permits(access, it.project_scope) and rules.destination_permits(access, it.local_only) for it in items)
            ctx = " ".join([infos.get(e.eid, ""), *(f"{(it.provenance.title or '')} {(it.provenance.speaker or '')} {(it.project_scope or '')}" for it in items if it)])
            out[e.eid] = validate.Evidence(tuple(self.env.logical_key(k) for k in e.ref_keys), html.unescape(texts.get(e.eid, "")), ctx, ok)
        return out
