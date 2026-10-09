"""Question pool for corpus v2, generated from the fact registry (facts_v2.json): every gold source, answerability label and forbidden pattern is DERIVED from the registry, never typed twice.

Labels: ESTABLISHED, CONFLICTED, PARTIAL, UNESTABLISHED (reasons: wrong_entity, no_record, unauthorized), SUPERSEDED. Three phrasings per relation: 0 and 1 are for design, 2 is a paraphrase used only
in the acceptance set. `held_out` marks relations and projects withheld from the design of the C1 lexicon and matcher.

    python questions.py     # writes pool_v2.json, cases_dev11.json (design), cases_dev12.json (acceptance, authored now; frozen by its manifest before any ablation result is read)"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import gen
from make_cases import case

WORDS = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen", 20: "twenty", 25: "twenty-five",
         30: "thirty", 35: "thirty-five", 40: "forty", 45: "forty-five", 50: "fifty", 55: "fifty-five", 60: "sixty", 65: "sixty-five", 70: "seventy", 75: "seventy-five", 80: "eighty"}
registry = json.loads((HERE / "facts_v2.json").read_text())
FACTS = registry["facts"]
PROJECTS = registry["projects"]
OWNER_PROFILE = "owner_private"


def val_re(v) -> list[str]:
    if isinstance(v, int):
        alts = [rf"\b{v}\b"]
        if v in WORDS:
            alts.append(rf"\b{WORDS[v]}\b")
        return alts
    if isinstance(v, str) and " " in v and v.replace(" ", "").isalpha() and v.split()[0][0].isupper() and len(v.split()) == 2:  # a person
        return [re.escape(v.split()[0].lower()), re.escape(v.lower())]
    return [re.escape(str(v).lower())]


def esc(s: str) -> str:
    return re.escape(s)


Q = {
    "owner": lambda sub: [f"Who owns the {sub}?", f"Who is responsible for the {sub}?", f"Whose job is it to look after the {sub}?"],
    "lead": lambda sub: [f"Who leads {sub}?", f"Who is the {sub} lead?", f"Who is in charge of {sub}?"],
    "retry_limit": lambda sub: [f"How many times does the {sub} retry a failed job?", f"What is the retry limit of the {sub}?", f"How often is a failed job on the {sub} tried again before it is parked?"],
    "default_model": lambda sub: [f"Which model does {sub} use by default?", f"What is {sub}'s default model?", f"Which model is {sub} running as its default?"],
    "runs_on": lambda sub: [f"Where does {sub} run?", f"Which host serves {sub}?", f"On what hardware is {sub} served?"],
    "rollback_window": lambda sub: [f"What is the rollback window for {sub}?", f"How long do I have to roll back a failed {sub} deploy?", f"Within how many minutes must a {sub} rollback happen?"],
    "support_hours": lambda sub: [f"What are {sub}'s support hours?", f"When is {sub} support open on weekdays?", f"When can I reach {sub}?"],
    "decision": lambda sub: [f"What was decided about {sub}'s default model?", f"What did the {sub} planning decide on the model?", f"Which model did the {sub} team agree to keep?"],
    "attends": lambda sub: [f"Who attended the {sub} planning meeting?", f"Who was in the {sub} planning meeting?", f"Which people took part in the {sub} planning?"],
    "reviews": lambda sub: [f"What is {sub} reviewing?", f"What does {sub} review?", f"What review is {sub} responsible for?"],
    "on_call": lambda sub: [f"Who is on call for {sub}?", f"Who has the on-call duty for {sub}?", f"Who covers {sub} out of hours?"],
    "budget_through": lambda sub: [f"Through when is the {sub} budget approved?", f"Until which month is {sub} funded?", f"How long does the {sub} budget run?"],
    "deadline": lambda sub: [f"By when does {sub} have to circulate the written summary?", f"What is {sub}'s deadline for the written summary?", f"When must {sub} send the written summary?"],
}
NO_RECORD = {  # relations that are recorded for nobody
    "security_reviewer": (lambda pr: [f"Who is the security reviewer for {pr}?", f"Who signs off {pr} security?", f"Which person approves {pr} security changes?"], r"signs off|reviewer|approves"),
    "max_message_size": (lambda pr: [f"What is the maximum message size of the {PROJECTS[pr]['system']} {PROJECTS[pr]['kind']}?", f"How large can a {PROJECTS[pr]['system']} message be?", f"What size limit applies to {PROJECTS[pr]['system']} messages?"], r"\b\d+\s?(?:kb|mb|bytes)\b"),
    "vacation": (lambda pr: [f"When is the {pr} lead's next vacation?", f"When will the {pr} lead be away next?", f"Which dates is the {pr} lead on leave?"], r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b"),
}


def subject_token(f) -> str:
    return f["subject"]


def cat_for(label, reason=None):
    return {"ESTABLISHED": "single_source", "CONFLICTED": "conflict", "PARTIAL": "partial_evidence", "SUPERSEDED": "supersession"}.get(label) or {"wrong_entity": "wrong_entity", "no_record": "no_evidence", "unauthorized": "authorization"}[reason]


def build_pool() -> list[dict]:
    pool: list[dict] = []
    by_rel: dict[str, list[dict]] = {}
    for f in FACTS:
        by_rel.setdefault(f["relation"], []).append(f)

    def add(label, reason, relation, subject, phr, question, *, held_out, sibling_projects=(), **kw):
        pool.append({**case(f"V2-{len(pool) + 1:04d}", cat_for(label, reason), question, access=OWNER_PROFILE, **kw),
                     "label": label, "reason": reason, "relation": relation, "subject": subject, "phrasing": phr, "held_out": bool(held_out or phr == 2)})

    for relation, facts in by_rel.items():
        if relation not in Q:
            continue
        for f in facts:
            ho = f["held_out"] or relation in gen.HELD_OUT_RELATIONS
            for phr, question in enumerate(Q[relation](f["subject"] if relation != "attends" else re.sub(r"^mt-", "", f["subject"]).title())):
                if f["state"] == "established":
                    add("ESTABLISHED", None, relation, f["subject"], phr, question, held_out=ho, gold=f["refs"], required=[val_re(f["value"] if not isinstance(f["value"], list) else f["value"][0]), *([val_re(f["value"][1])] if isinstance(f["value"], list) else [])])
                elif f["state"] == "conflicted":
                    add("CONFLICTED", None, relation, f["subject"], phr, question, held_out=ho, gold=f["refs"], required=[val_re(f["value"]), val_re(f["conflict_value"])], conflict=True)
                elif f["state"] == "unrecorded":
                    sib = [g for g in facts if g["state"] != "unrecorded"][:2]
                    forb = [rf"{esc(f['subject'].split()[0])}(?:'s)?(?: \w+){{0,3}} (?:is|are|was) {val_re(g['value'])[0]}" for g in sib if isinstance(g["value"], str)]
                    add("UNESTABLISHED", "wrong_entity", relation, f["subject"], phr, question, held_out=ho, abstain=True, distractors=[r for g in sib for r in g["refs"]][:3], forbidden=forb, note="relation recorded only for sibling entities")
    # relations recorded for only some projects: the others are unestablished with sibling evidence in the corpus
    for relation in ("decision", "budget_through", "attends"):
        recorded = {f["subject"] for f in by_rel[relation]}
        for pr in PROJECTS:
            subj = pr if relation != "attends" else f"mt-{gen.slug(pr)}"
            if subj in recorded:
                continue
            sib = by_rel[relation][:2]
            name = pr
            for phr, question in enumerate(Q[relation](name)):
                add("UNESTABLISHED", "wrong_entity", relation, name, phr, question, held_out=gen.slug(pr) in gen.HELD_OUT_PROJECTS or relation in gen.HELD_OUT_RELATIONS, abstain=True, distractors=[r for g in sib for r in g["refs"]][:3],
                    forbidden=[rf"{esc(pr)}(?:'s)?(?: \w+){{0,3}} (?:is|are|was|through) {val_re(g['value'])[0]}" for g in sib if isinstance(g["value"], str) and relation == "budget_through"], note="relation recorded only for other projects")
    for rel, (fn, forb) in NO_RECORD.items():
        for pr in PROJECTS:
            for phr, question in enumerate(fn(pr)):
                add("UNESTABLISHED", "no_record", rel, pr, phr, question, held_out=gen.slug(pr) in gen.HELD_OUT_PROJECTS, abstain=True, distractors=[f"document:doc-{gen.slug(pr)}-arch"], forbidden=[forb], note="recorded for nobody")
    for f in by_rel.get("incident_auditor", []):
        pr = f["subject"]
        for phr, question in enumerate([f"Who audits the {pr} build logs?", f"Who is going to audit the {pr} build logs after the incident?", f"Which person checks the {pr} build logs?"]):
            add("UNESTABLISHED", "unauthorized", "incident_auditor", pr, phr, question, held_out=gen.slug(pr) in gen.HELD_OUT_PROJECTS, abstain=True, excluded=f["refs"], canaries=[val_re(f["value"])[0]], distractors=[f"document:doc-{gen.slug(pr)}-arch"], note="only in a sensitive record")
    for f in by_rel.get("default_model_history", []):
        pr = f["subject"]
        for phr, question in enumerate([f"Which model did {pr} use by default in March?", f"What was {pr}'s default model before October?", f"Which model did {pr} use before it switched?"]):
            add("SUPERSEDED", None, "default_model_history", pr, phr, question, held_out=False, temporal="include_historical", gold=f["refs"], required=[val_re(f["value"])])
    for pr, info in PROJECTS.items():
        ho = gen.slug(pr) in gen.HELD_OUT_PROJECTS
        did = f"document:doc-{gen.slug(pr)}-arch"
        model = info["model"]
        for phr, question in enumerate([f"Which model does the deep path serve for {pr}?", f"Which model do {pr}'s scheduled jobs run on?", f"Which model sits behind the {pr} deep path?"]):
            add("PARTIAL", None, "deep_path_model", pr, phr, question, held_out=ho, gold=[did], required=[[r"deep path", r"scheduled"]], forbidden=[rf"(?:deep path|scheduled jobs)[^.]{{0,30}}\b(?:serves?|runs?|uses?|is)\b[^.]{{0,15}}{esc(model.lower())}"], note="the document names the model and the deep path in separate sentences without joining them")
        owner = next((f for f in by_rel["owner"] if f["subject"].startswith(info["system"]) and f["state"] == "established"), None)
        if owner:
            for phr, (question) in enumerate([f"Who owns the {info['system']} {info['kind']}, and what is its maximum message size?", f"Who is responsible for the {info['system']} {info['kind']} and how big can a message be?", f"Whose job is the {info['system']} {info['kind']}, and what size limit does it have?"]):
                add("PARTIAL", None, "owner+max_message_size", pr, phr, question, held_out=ho, gold=owner["refs"], required=[val_re(owner["value"])], forbidden=[r"\b\d+\s?(?:kb|mb|bytes)\b"], note="second part recorded for nobody")
    return pool


def sample(pool, rnd, n, pred, per_label):
    chosen = []
    for label, k in per_label.items():
        cand = [c for c in pool if pred(c) and c["label"] + (":" + c["reason"] if c["reason"] else "") == label]
        rnd.shuffle(cand)
        chosen += cand[:k]
    return chosen[:n]


if __name__ == "__main__":
    rnd = random.Random(1212)
    pool = build_pool()
    (HERE / "pool_v2.json").write_text(json.dumps({"purpose": "all generated, labelled questions over corpus v2", "cases": pool}, indent=0) + "\n")
    design = [c for c in pool if not c["held_out"] and c["phrasing"] in (0, 1)]
    held = [c for c in pool if c["held_out"]]
    per = {"ESTABLISHED": 14, "CONFLICTED": 6, "UNESTABLISHED:wrong_entity": 12, "UNESTABLISHED:no_record": 6, "UNESTABLISHED:unauthorized": 3, "PARTIAL": 10, "SUPERSEDED": 3}
    d11 = sample(design, rnd, 80, lambda c: True, per)
    per12 = {"ESTABLISHED": 28, "CONFLICTED": 10, "UNESTABLISHED:wrong_entity": 22, "UNESTABLISHED:no_record": 10, "UNESTABLISHED:unauthorized": 5, "PARTIAL": 16, "SUPERSEDED": 0}
    d12 = sample(held, rnd, 100, lambda c: True, per12)
    # superseded questions exist only for design projects (no held-out history facts); the acceptance set covers temporal claims through conflicts and cross-section cases instead

    def renumber(cases, prefix):
        out = []
        for i, c in enumerate(cases, 1):
            c = dict(c)
            c["id"] = f"{prefix}-{i:03d}"
            out.append(c)
        return out

    (HERE.parent / "cases_dev11.json").write_text(json.dumps({"version": 1, "split": "dev11", "corpus": "corpus_v2", "purpose": "design and ablation cases for the groundedness milestone (invented corpus v2)", "cases": renumber(d11, "D11")}, indent=1) + "\n")
    (HERE.parent / "cases_dev12.json").write_text(json.dumps({"version": 1, "split": "dev12", "corpus": "corpus_v2", "purpose": "one-shot acceptance cases (held-out relations, held-out projects, unseen paraphrases); never tuned against", "cases": renumber(d12, "D12")}, indent=1) + "\n")
    import collections
    print("pool", len(pool), dict(collections.Counter(c["label"] + (":" + c["reason"] if c["reason"] else "") for c in pool)))
    print("dev11", len(d11), "dev12", len(d12))
