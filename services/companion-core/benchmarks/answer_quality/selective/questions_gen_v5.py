"""Question generator for corpus v5 worlds (owner decision 2026-10-15). Uses the v4 atom pool, adds the four existence-relation families with their six evidence conditions, and renders every question from the NEW
bank E only (`banks_e.py`, frozen by hash before any scorer-v3 evaluation). Atoms carry `fact_key` (world-independent underlying fact: subject, relation family, condition) and `world` so that paraphrases of one
underlying fact are never counted as independent events. Design relations and non-held-out projects only; no dev16 candidate, no bank C/D phrasing."""
from __future__ import annotations

import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corpus_gen_v5 as g5
import questions_gen as qg
from banks_e import BANK_E

for _rel, _fam in g5.FAMILIES.items():  # register the new relations with the v4 atom builder (in memory only; questions_gen.py is untouched)
    qg.CUES[_rel] = _fam["cue"]
    qg.KIND[_rel] = "bool"

PRESENCE_RE = r"\byes\b|\bthere is (?:a|an)\b|\bhas (?:a|an)\b|\bdoes have\b|\bexists?\b|\bis (?:a|an) [a-z\- ]{0,20}(?:runbook|rotation|channel|page)\b"
ABSENCE_RE = r"\bhas no\b|\bthere is no\b|\bdoes not have\b|\bdoesn['’]t have\b|\bwithout (?:a|an)\b|\bno (?:[a-z\-]+ ){0,2}(?:runbook|rotation|channel|status page|page)\b"
COUNTS_V5 = {"control_supported": 15, "control_unsupported": 30, "mixed": 30, "multipart": 25, "conflict": 45, "unknown_actor": 35, "negative": 40, "temporal": 60}


class Pool5(qg.Pool):
    """The v4 atom pool with bank-E rendering and the existence atoms of the corpus's v5 facts."""

    def __init__(self, registry: dict, world: int):
        super().__init__()
        self.atoms = [a for a in self.atoms if not a["held_out"]]
        for a in self.atoms:
            a["world"] = world
            a["fact_key"] = f"{a['relation']}|{a['subject']}|{a.get('base_relation', '')}|{a['status'] if a['status'] in ('SUPPORTED', 'HISTORICAL') else 'x'}"
        n = 0
        for f in registry["facts"]:
            if f["relation"] not in g5.FAMILIES:
                continue
            fam = g5.FAMILIES[f["relation"]]
            status = g5.STATUS_OF[f["state"]]
            n += 1
            a = qg.atom(f"B{world:02d}{n:04d}", status, f["relation"], f["subject"], kind="bool", cue_re=fam["cue"], sources=f["refs"] if status != "NEGATIVE_UNSUPPORTED" else [])
            if status == "SUPPORTED":
                a.update(values=[[PRESENCE_RE]], display=["yes"])
            elif status == "NEGATIVE_SUPPORTED":
                a.update(values=[[ABSENCE_RE]], display=["no"])
            elif status == "CONFLICTED":
                a.update(values=[[PRESENCE_RE], [ABSENCE_RE]], display=["yes", "no"])
            a.update(project=f["subject"], pretty=f["subject"], held_out=False, world=world, condition=f["state"], fact_key=f"{f['relation']}|{f['subject']}|{f['state']}", family="existence")
            a["severe"] = status in ("NEGATIVE_UNSUPPORTED", "CONFLICTED")
            self.atoms.append(a)

    def question_fragment(self, a: dict, bank: str, k: int) -> str:
        rel = a["relation"]
        text = BANK_E[rel][k % 2]
        if rel in ("default_model_history",):
            return text.format(x=a["pretty"], s=a["subject"])
        if rel == "retry_limit_history":
            return text.format(x=a["subject"], s=a["subject"])
        if rel == "order_figure":
            return text.format(x=a["pretty"], s=a["subject"])
        return text.format(x=a["pretty"], s=a["subject"])


def build_cases(registry: dict, world: int) -> list[dict]:
    qg.REG, qg.FACTS, qg.PROJECTS = registry, registry["facts"], registry["projects"]
    pool = Pool5(registry, world)
    rnd = random.Random(world * 100 + 29)
    cases = qg.build_cases(pool, rnd, False, COUNTS_V5, f"W{world}")
    for c in cases:
        c["bank"] = "E"
    existence = [a for a in pool.atoms if a.get("family") == "existence"]
    supported = [a for a in pool.atoms if a["status"] == "SUPPORTED" and a.get("family") != "existence"]
    rnd.shuffle(supported)
    for k, a in enumerate(existence, 1):  # every existence atom is asked once alone
        cases.append(_case(f"W{world}", len(cases) + 1, "existence", [a], k))
    for i, a in enumerate(existence[: len(existence) // 2]):  # and half of them next to an unrelated supported part
        partner = next((s for s in supported if s["project"] != a["project"]), None)
        if partner:
            cases.append(_case(f"W{world}", len(cases) + 1, "existence_mixed", [a, partner], 100 + i))
    return cases


def _case(prefix, n, family, atoms, k) -> dict:
    frags = [BANK_E[a["relation"]][k % 2].format(x=a["pretty"], s=a["subject"]) for a in atoms]
    return {"id": f"{prefix}-{n:03d}", "family": family, "question": qg.join(frags), "access": qg.OWNER_PROFILE, "attached_meeting": None, "temporal": "current", "modality": "text",
            "gold_refs": sorted({s for a in atoms for s in a["sources"]}), "distractor_refs": [], "abstain": all(a["status"] in ("UNSUPPORTED", "NEGATIVE_UNSUPPORTED") for a in atoms),
            "expect_conflict": any(a["status"] == "CONFLICTED" for a in atoms), "required": [], "forbidden": [], "canaries": [], "plants": [], "followed": [], "excluded_refs": [], "note": "", "category": "single_source",
            "atoms": atoms, "bank": "E", "held_out": False}
