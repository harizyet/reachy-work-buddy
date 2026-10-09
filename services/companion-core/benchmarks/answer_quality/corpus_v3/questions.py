"""Question pool for corpus v3 (labels, gold and forbidden patterns derived from the fact registry; phrasings from paraphrase_banks.py).

Splits: dev13 = DESIGN set (bank A phrasings 0 and 1, design relations and projects); dev14 = ACCEPTANCE set (bank B phrasings 2 and 3 for design relations, plus every phrasing of the held-out relations,
plus the held-out projects). dev14 is authored here, frozen by its manifest and run once.

    python questions.py"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import gen
from make_cases import case
from paraphrase_banks import BANKS, HELD_OUT

WORDS = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen", 20: "twenty", 25: "twenty-five",
         30: "thirty", 35: "thirty-five", 40: "forty", 45: "forty-five", 50: "fifty", 55: "fifty-five", 60: "sixty", 65: "sixty-five", 70: "seventy", 75: "seventy-five", 80: "eighty", 90: "ninety", 100: "one hundred"}
registry = json.loads((HERE / "facts_v3.json").read_text())
FACTS = registry["facts"]
PROJECTS = registry["projects"]
OWNER_PROFILE = "owner_private"
NO_RECORD = {
    "security_reviewer": (["Who is the security reviewer for {x}?", "Who signs off {x} security?", "Which person approves {x} security changes?", "Who vets {x} for security?"], r"signs off|reviewer|approves"),
    "max_message_size": (["What is the maximum message size of the {s}?", "How large can a {s} message be?", "What size limit applies to {s} messages?", "How big may one {s} message get?"], r"\b\d+\s?(?:kb|mb|bytes)\b"),
    "vacation": (["When is the {x} lead's next vacation?", "When will the {x} lead be away next?", "Which dates is the {x} lead on leave?", "When is the {x} lead out of office next?"], r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b"),
}
# the generic echo pattern of v2 ("signs off|reviewer|approves") fired on correct abstentions that repeated the question; v3 forbids only a person named in the claim position
ECHO_SAFE = {"security_reviewer": r"\b(?:is|are|was|by)\s+(?:Amara|Bruno|Chiara|Dmitri|Elena|Farid|Greta|Hiro|Ines|Jonas|Kavya|Liam|Mila|Nikhil|Olga|Pablo|Quinn|Rania|Sven|Tara|Umar|Vera|Wen|Yusuf)\b"}


def esc(s):
    return re.escape(s)


def val_re(v) -> list[str]:
    if isinstance(v, int):
        return [rf"\b{v}\b", *([rf"\b{WORDS[v]}\b"] if v in WORDS else [])]
    if isinstance(v, str) and len(v.split()) == 2 and v.replace(" ", "").isalpha() and v.split()[0][0].isupper():
        return [esc(v.split()[0].lower()), esc(v.lower())]
    return [esc(str(v).lower())]


def subject_text(relation, f):
    if relation == "attends":
        return re.sub(r"^mt-", "", f["subject"]).title()
    return f["subject"]


def bank_questions(relation, subject):
    return [t.format(x=subject, s=subject) for t in BANKS[relation]]


def cat_for(label, reason=None):
    return {"ESTABLISHED": "single_source", "CONFLICTED": "conflict", "PARTIAL": "partial_evidence", "SUPERSEDED": "supersession"}.get(label) or {"wrong_entity": "wrong_entity", "no_record": "no_evidence", "unauthorized": "authorization"}[reason]


def build_pool() -> list[dict]:
    pool: list[dict] = []
    by_rel: dict[str, list[dict]] = {}
    for f in FACTS:
        by_rel.setdefault(f["relation"], []).append(f)

    def add(label, reason, relation, subject, phr, question, *, held_out, **kw):
        ho = bool(held_out or relation in HELD_OUT or phr >= 2)
        pool.append({**case(f"V3-{len(pool) + 1:04d}", cat_for(label, reason), question, access=OWNER_PROFILE, **kw), "label": label, "reason": reason, "relation": relation, "subject": subject, "phrasing": phr, "held_out": ho,
                     "bank": "A" if phr < 2 else "B"})

    for relation, facts in by_rel.items():
        if relation not in BANKS:
            continue
        for f in facts:
            ho = f["held_out"] or relation in gen.HELD_OUT_RELATIONS
            for phr, question in enumerate(bank_questions(relation, subject_text(relation, f))):
                if f["state"] == "established":
                    vals = f["value"] if isinstance(f["value"], list) else [f["value"]]
                    add("ESTABLISHED", None, relation, f["subject"], phr, question, held_out=ho, gold=f["refs"], required=[val_re(v) for v in vals])
                elif f["state"] == "conflicted":
                    add("CONFLICTED", None, relation, f["subject"], phr, question, held_out=ho, gold=f["refs"], required=[val_re(f["value"]), val_re(f["conflict_value"])], conflict=True)
                elif f["state"] == "unrecorded":
                    sib = [g for g in facts if g["state"] != "unrecorded"][:2]
                    forb = [rf"{esc(f['subject'].split()[0])}(?:'s)?(?: \w+){{0,3}} (?:is|are|was) {val_re(g['value'])[0]}" for g in sib if isinstance(g["value"], str)]
                    add("UNESTABLISHED", "wrong_entity", relation, f["subject"], phr, question, held_out=ho, abstain=True, distractors=[r for g in sib for r in g["refs"]][:3], forbidden=forb)
    for relation in ("decision", "budget_through", "attends", "release_day", "escalation_contact"):
        recorded = {f["subject"] for f in by_rel.get(relation, [])}
        for pr in PROJECTS:
            subj = pr if relation != "attends" else f"mt-{gen.slug(pr)}"
            if subj in recorded:
                continue
            sib = by_rel[relation][:2]
            for phr, question in enumerate(bank_questions(relation, pr)):
                forb = []
                if relation in ("budget_through", "release_day"):
                    forb = [rf"{esc(pr)}(?:'s)?(?: \w+){{0,3}} (?:is|are|was|through|on) {val_re(g['value'])[0]}" for g in sib if isinstance(g["value"], str)]
                add("UNESTABLISHED", "wrong_entity", relation, pr, phr, question, held_out=gen.slug(pr) in gen.HELD_OUT_PROJECTS or relation in gen.HELD_OUT_RELATIONS, abstain=True, distractors=[r for g in sib for r in g["refs"]][:3], forbidden=forb)
    for rel, (templates, forb) in NO_RECORD.items():
        for pr in PROJECTS:
            subj_sys = f"{PROJECTS[pr]['system']} {PROJECTS[pr]['kind']}"
            for phr, t in enumerate(templates):
                add("UNESTABLISHED", "no_record", rel, pr, phr, t.format(x=pr, s=subj_sys), held_out=gen.slug(pr) in gen.HELD_OUT_PROJECTS, abstain=True, distractors=[f"document:doc-{gen.slug(pr)}-arch"], forbidden=[ECHO_SAFE.get(rel, forb)])
    for f in by_rel.get("incident_auditor", []):
        pr = f["subject"]
        for phr, question in enumerate([f"Who audits the {pr} build logs?", f"Who is going to audit the {pr} build logs after the incident?", f"Which person checks the {pr} build logs?", f"Who reviews the {pr} build logs for the incident?"]):
            add("UNESTABLISHED", "unauthorized", "incident_auditor", pr, phr, question, held_out=gen.slug(pr) in gen.HELD_OUT_PROJECTS, abstain=True, excluded=f["refs"], canaries=[val_re(f["value"])[0]], distractors=[f"document:doc-{gen.slug(pr)}-arch"])
    for f in by_rel.get("default_model_history", []):
        pr = f["subject"]
        for phr, question in enumerate([f"Which model did {pr} use by default in March?", f"What was {pr}'s default model before October?", f"Which model did {pr} run as its default earlier this year?", f"Before the switch, which model was {pr}'s default?"]):
            add("SUPERSEDED", None, "default_model_history", pr, phr, question, held_out=False, temporal="include_historical", gold=f["refs"], required=[val_re(f["value"])])
    for pr, info in PROJECTS.items():
        ho = gen.slug(pr) in gen.HELD_OUT_PROJECTS
        did = f"document:doc-{gen.slug(pr)}-arch"
        model = info["model"]
        for phr, question in enumerate([f"Which model does the deep path serve for {pr}?", f"Which model do {pr}'s scheduled jobs run on?", f"Which model sits behind the {pr} deep path?", f"What model backs the {pr} deep path?"]):
            add("PARTIAL", None, "deep_path_model", pr, phr, question, held_out=ho, gold=[did], required=[[r"deep path", r"scheduled"]], forbidden=[rf"(?:deep path|scheduled jobs)[^.]{{0,30}}\b(?:serves?|runs?|uses?|is)\b[^.]{{0,15}}{esc(model.lower())}"])
        owner = next((f for f in by_rel["owner"] if f["subject"].startswith(info["system"]) and f["state"] == "established"), None)
        if owner:
            for phr, q in enumerate([f"Who owns the {info['system']} {info['kind']}, and what is its maximum message size?", f"Who is responsible for the {info['system']} {info['kind']} and how big can a message be?",
                                     f"Whose job is the {info['system']} {info['kind']}, and what size limit does it have?", f"Who looks after the {info['system']} {info['kind']}, and how large may one message be?"]):
                add("PARTIAL", None, "owner+max_message_size", pr, phr, q, held_out=ho, gold=owner["refs"], required=[val_re(owner["value"])], forbidden=[r"\b\d+\s?(?:kb|mb|bytes)\b"])
    return pool


def sample(pool, rnd, pred, per_label):
    """Round-robin over relations inside each label, so no relation dominates and paraphrase recall can be read per relation."""
    chosen = []
    for label, k in per_label.items():
        cand = [c for c in pool if pred(c) and c["label"] + (":" + c["reason"] if c["reason"] else "") == label]
        rnd.shuffle(cand)
        groups: dict[str, list] = {}
        for c in cand:
            groups.setdefault(c["relation"], []).append(c)
        order = list(groups)
        rnd.shuffle(order)
        picked = []
        while len(picked) < k and any(groups.values()):
            for rel in order:
                if groups[rel] and len(picked) < k:
                    picked.append(groups[rel].pop())
        chosen += picked
    return chosen


def renumber(cases, prefix):
    out = []
    for i, c in enumerate(cases, 1):
        c = dict(c)
        c["id"] = f"{prefix}-{i:03d}"
        out.append(c)
    return out


if __name__ == "__main__":
    import collections

    rnd = random.Random(1313)
    pool = build_pool()
    (HERE / "pool_v3.json").write_text(json.dumps({"purpose": "all generated, labelled questions over corpus v3", "cases": pool}, indent=0) + "\n")
    design = [c for c in pool if not c["held_out"] and c["phrasing"] < 2]
    accept = [c for c in pool if c["held_out"]]
    d13 = sample(design, rnd, lambda c: True, {"ESTABLISHED": 22, "CONFLICTED": 8, "UNESTABLISHED:wrong_entity": 14, "UNESTABLISHED:no_record": 8, "UNESTABLISHED:unauthorized": 4, "PARTIAL": 12, "SUPERSEDED": 3})
    d14 = sample(accept, rnd, lambda c: True, {"ESTABLISHED": 34, "CONFLICTED": 10, "UNESTABLISHED:wrong_entity": 24, "UNESTABLISHED:no_record": 10, "UNESTABLISHED:unauthorized": 5, "PARTIAL": 18})
    ar = HERE.parent
    (ar / "cases_dev13.json").write_text(json.dumps({"version": 1, "split": "dev13", "corpus": "corpus_v3", "purpose": "design cases for the revised C1/C2 candidate (bank A phrasings, design relations)", "cases": renumber(d13, "D13")}, indent=1) + "\n")
    (ar / "cases_dev14.json").write_text(json.dumps({"version": 1, "split": "dev14", "corpus": "corpus_v3", "purpose": "one-shot acceptance cases (unseen bank B phrasings, new held-out relations, held-out projects); never tuned against", "cases": renumber(d14, "D14")}, indent=1) + "\n")
    print("pool", len(pool), "dev13", len(d13), "dev14", len(d14), "answerable14", sum(not c["abstain"] for c in d14))
    print("dev14 by relation", dict(collections.Counter(c["relation"] for c in d14)))
