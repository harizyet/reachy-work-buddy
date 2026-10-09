"""Harness conditions for the section-level coverage experiment. Subclasses the frozen `Conditions` without modifying it: `+sec` runs the section-level assessor in place of the item-level one
(same note, same single retry, same builder), `+secd` is the variant that also treats a name's following word as part of the name. Everything else about a request is identical to `+suff`."""
from __future__ import annotations

from companion_core.knowledge.sufficiency import (
    abstention,
    assess,
    coverage_note,
    pieces_from_items,
    retry_query,
)
from companion_core.knowledge.sufficiency_section import assess_sections

from aq.conditions import Conditions


class SecConditions(Conditions):
    sec = None  # None, "sec" or "secd"

    async def prepare(self, name, case):
        base, *mods = name.split("+")
        self.sec = "secd" if "secd" in mods else ("sec" if "sec" in mods else None)
        mapped = "+".join([base, *["suff" if m in ("sec", "secd") else m for m in mods]])
        return await super().prepare(mapped, case)

    async def _sufficiency(self, name, case, access, pinned, items, prepared):
        if self.sec is None:
            return await super()._sufficiency(name, case, access, pinned, items, prepared)
        question = case["question"]

        def judge(its):
            return assess_sections(question, pieces_from_items(its), descriptors=self.sec == "secd")

        first = judge(items)
        prepared.suff = {"first": first.verdict, "retried": False, "final": first.verdict, "item_level": assess(question, pieces_from_items(items)).verdict}
        final = first
        query = retry_query(first)
        if query:
            again = await self.retriever(name).retrieve(query, access, pinned, temporal=case["temporal"], limit=10)
            seen = {i.ref.key for i in items}
            extra = [i for i in again.bundle.items if i.ref.key not in seen]
            prepared.suff.update(retried=True, retry_query=query, retry_added=len(extra))
            if extra:
                items = items + extra[:3]
                final = judge(items)
        prepared.suff["final"] = final.verdict
        if self.gate:
            reply = abstention(final)
            if reply is not None:
                prepared.fixed_reply = reply
                prepared.suff["gated"] = True
        return items, coverage_note(final)
