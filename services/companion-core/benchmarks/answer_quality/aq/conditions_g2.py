"""Harness conditions for the scoped-readiness evaluation of the REVISED C1/C2 (corpus v3). Subclass of the groundedness conditions; the frozen originals (`c1f`, `c2n`, ...) still work as the comparator.
  +r1   revised C1, nothing-asserts => show nothing        +r1q  revised C1, related records quarantined in a non-evidence block        +r1d  revised C1, nothing-asserts and relation unrecognised => baseline records
  +r2   revised C2 annotation (hedged note)                +c3   attendee route (unchanged)
Every revised arm records the time of each stage of the path: retrieval of 30 candidates, C1 selection, C2, the builder, and (in run_g2) the model call and the end-to-end preparation."""
from __future__ import annotations

import time

from companion_core.knowledge.context import _is_historical
from companion_core.knowledge.grounding import routes
from companion_core.knowledge.grounding.revised import answerability as ans2
from companion_core.knowledge.grounding.revised import propositions as props2
from companion_core.knowledge.sufficiency import pieces_from_items
from companion_core.semantic import access as rules
from kbench.security import access_context

from aq.conditions import Prepared, base_messages
from aq.conditions_g import NOW, GConditions
from shared.models.response import Privacy

R_MODS = {"r1", "r1d", "r1q", "r2"}


class GConditions2(GConditions):
    async def prepare(self, name, case):
        base, *mods = name.split("+")
        if base == "b1a" and (set(mods) & R_MODS):
            self.g = {m for m in mods if m in R_MODS | {"c3"}}
            prep = await self._prepare_r(case)
            prep.g_mods = sorted(self.g)
            prep.evidence = self._evidence(prep, case) if prep.rendered is not None else {}
            return prep
        prep = await super().prepare(name, case)
        prep.timings = getattr(prep, "timings", {})
        return prep

    async def _prepare_r(self, case) -> Prepared:
        profile = self.spec["access_profiles"][case["access"]]
        access = access_context(profile)
        prepared = Prepared(messages=base_messages(case))
        t0 = time.perf_counter()
        res = await self.retriever("b1a").retrieve(case["question"], access, None, temporal=case["temporal"], limit=30)
        t1 = time.perf_counter()
        candidates = list(res.bundle.items)
        prepared.retrieval_dropped = dict(res.bundle.dropped)
        prepared.retrieval_ms = (t1 - t0) * 1000
        skip = {i for i, it in enumerate(candidates) if case["temporal"] != "include_historical" and _is_historical(it, NOW)}
        pieces = pieces_from_items(candidates)
        sel = props2.select(case["question"], pieces, known_people=self.people, skip=skip)
        t2 = time.perf_counter()
        state = ans2.assess(sel)
        t3 = time.perf_counter()
        baseline = candidates[:10]
        quarantined = None
        if "r1" in self.g or "r1q" in self.g:
            shown = props2.reorder(candidates, sel, "remove", baseline=baseline)
            if "r1q" in self.g:
                quarantined = props2.quarantine_text(case["question"], pieces, sel)
        elif "r1d" in self.g:
            shown = props2.reorder(candidates, sel, "decline", baseline=baseline)
        else:
            shown = baseline
        info = {"state": state.state, "reason": state.reason, "selected": len(sel.selected), "shown": len(shown), "candidates": len(candidates), "relation": sel.propositions[0].relation,
                "calibrated_note": "r2" in self.g}
        prepared.timings = {"retrieval30_ms": prepared.retrieval_ms, "select_ms": (t2 - t1) * 1000, "c2_ms": (t3 - t2) * 1000}
        if "c3" in self.g:
            meetings = [m for m in self.spec["meetings"] if rules.within_ceiling(Privacy(m["sensitivity"]), access.sensitivity_ceiling)]
            routed = routes.route_attendees(case["question"], meetings)
            if routed is not None:
                prepared.fixed_reply = routed.text
                info["routed"] = True
                prepared.g = info
                return prepared
        parts = [x for x in (ans2.note(state) if "r2" in self.g else None, quarantined) if x]
        self.note = "\n".join(parts) if parts else None
        try:
            prepared = self._finish(case, prepared, shown, access, candidates=len(shown))
        finally:
            self.note = None
        prepared.timings = {**prepared.timings, "build_ms": prepared.build_ms}
        prepared.g = info
        prepared.retrieval_ms = (t1 - t0) * 1000
        return prepared
