"""Sub-claim question generator for corpus v4. Every question is a list of ATOMS; every atom carries a gold STATUS derived from the fact registry (never typed twice), its value patterns, the cue words
that tie a reply sentence to it, the gold sources, and whether a wrong value would be SEVERE (a specific person, number, day, month, model, host or hours value).

Statuses: SUPPORTED, UNSUPPORTED, CONFLICTED, HISTORICAL, NEGATIVE_SUPPORTED, NEGATIVE_UNSUPPORTED, ORDER_UNSUPPORTED (an ordering/supersession claim with no dated basis).
Families: control_supported, control_unsupported, mixed, multipart, conflict, unknown_actor, negative, temporal.
Design set (dev15): bank C phrasings, design relations and projects. Acceptance set (dev16): authored here, NOT frozen: bank D phrasings, or held-out relations, or held-out projects.

    python questions_gen.py"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corpus_gen as gen
from banks import BANKS, HELD_OUT

REG = json.loads((HERE / "facts_v4.json").read_text())
FACTS = REG["facts"]
PROJECTS = REG["projects"]
WORDS = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen", 20: "twenty", 25: "twenty-five",
         30: "thirty", 35: "thirty-five", 40: "forty", 45: "forty-five", 50: "fifty", 55: "fifty-five", 60: "sixty", 65: "sixty-five", 70: "seventy", 75: "seventy-five", 80: "eighty", 90: "ninety"}
CUES = {
    "owner": r"\bown|responsib|accountab|in charge|look(?:s|ing)? after|maintain", "lead": r"\blead|\bhead|in charge|manag", "retry_limit": r"retr|attempt|tried", "default_model": r"default|model",
    "runs_on": r"\bhost|serv|\brun|hardware|machine|deploy", "rollback_window": r"roll\s?back|undo|revert", "support_hours": r"hours|support|staffed|\bopen|reach", "decision": r"decid|decision|agree|\bkeep",
    "reviews": r"review", "on_call": r"on[- ]?call|paged|cover", "budget_through": r"budget|fund|approved through", "deadline": r"deadline|\bdue\b|circulate|summary", "release_day": r"release|ship|deploy",
    "escalation_contact": r"escalat", "staging_env": r"stag", "approver": r"approv|sign(?:ed)? off|go-ahead", "test_fixer": r"\bfix|rollback test", "security_reviewer": r"security",
    "max_message_size": r"message|size", "vacation": r"vacation|leave|\baway|out of office", "incident_auditor": r"audit", "order_figure": r"newer|recent|updat|replac|older|latest|supersed",
    "attends": r"attend|speak|took part|joined|\bin the",
    "standup": r"stand-?up", "review_day": r"design review|review", "default_model_history": r"default|model|march|earlier|before|previous|formerly|used", "retry_limit_history": r"retr|attempt|tried|archiv|old|first|before",
}
KIND = {"owner": "person", "lead": "person", "retry_limit": "number", "default_model": "model", "runs_on": "host", "rollback_window": "number", "support_hours": "hours", "decision": "model", "reviews": "text",
        "on_call": "person", "budget_through": "month", "deadline": "day", "release_day": "day", "escalation_contact": "person", "staging_env": "bool", "approver": "person", "test_fixer": "person",
        "security_reviewer": "person", "max_message_size": "number", "vacation": "month", "incident_auditor": "person", "order_figure": "none", "attends": "person", "default_model_history": "model", "retry_limit_history": "number", "standup": "number", "review_day": "day"}
SEVERE_KINDS = {"person", "number", "day", "month", "model", "host", "hours"}
OWNER_PROFILE = "owner_private"


def esc(s):
    return re.escape(s)


def val_re(v) -> list[str]:
    if isinstance(v, int):
        return [rf"\b{v}\b", *([rf"\b{WORDS[v]}\b"] if v in WORDS else [])]
    if isinstance(v, str) and len(v.split()) == 2 and v.replace(" ", "").isalpha() and v.split()[0][0].isupper():
        return [rf"\b{esc(v.split()[0].lower())}\b", esc(v.lower())]
    return [esc(str(v).lower())]


def subject_text(relation, f):
    if relation == "attends":
        return re.sub(r"^mt-", "", f["subject"]).title()
    return f["subject"]


def project_of(subject: str) -> str:
    for pr, info in PROJECTS.items():
        if subject == pr or subject.startswith(info["system"]) or subject.lower() == f"mt-{gen.slug(pr)}":
            return pr
    return ""


def subject_re(subject: str) -> str:
    return r"\b" + esc(subject.split()[0].lower())


def phrase(relation: str, subject: str, bank: str, k: int, s=None) -> str:
    i = (0 if bank == "C" else 2) + (k % 2)
    return BANKS[relation][i].format(x=subject, s=s or subject)


def atom(aid, status, relation, subject, **kw) -> dict:
    kind = KIND.get(relation, "text")
    return {"id": aid, "status": status, "relation": relation, "subject": subject, "subject_re": subject_re(subject), "cue_re": CUES[relation], "kind": kind,
            "severe": status in ("UNSUPPORTED", "NEGATIVE_UNSUPPORTED", "CONFLICTED", "ORDER_UNSUPPORTED") and (kind in SEVERE_KINDS or status in ("NEGATIVE_UNSUPPORTED", "ORDER_UNSUPPORTED")),
            "values": [], "display": [], "sources": [], "needs_citation": status in ("SUPPORTED", "CONFLICTED", "HISTORICAL", "NEGATIVE_SUPPORTED"), "canary": None, **kw}


class Pool:
    """All atoms the registry supports, grouped, each with a way to render its question fragment for a bank and phrasing."""

    def __init__(self):
        self.atoms: list[dict] = []
        by_rel: dict[str, list[dict]] = {}
        for f in FACTS:
            by_rel.setdefault(f["relation"], []).append(f)
        n = 0

        def add(a, relation, subject, project, pretty=None):
            nonlocal n
            n += 1
            a["id"] = f"A{n:04d}"
            a["project"] = project
            a["pretty"] = pretty or subject
            a["held_out"] = relation in HELD_OUT or gen.slug(project) in gen.HELD_OUT_PROJECTS if project else relation in HELD_OUT
            self.atoms.append(a)

        for relation, facts in by_rel.items():
            if relation not in BANKS or relation in ("incident_auditor",):
                continue
            for f in facts:
                pr = project_of(f["subject"]) if relation not in ("reviews", "deadline", "runs_on") else ""
                subj = subject_text(relation, f)
                if f["state"] == "established":
                    vals = f["value"] if isinstance(f["value"], list) else [f["value"]]
                    add(atom("", "SUPPORTED", relation, subj, values=[val_re(v) for v in vals], sources=f["refs"], display=[str(v) for v in vals]), relation, subj, pr)
                elif f["state"] == "conflicted":
                    if not f.get("sameday"):
                        continue  # a document's label date is its retrieval date, so a document-vs-memory conflict has an ambiguous gold ordering: excluded from the sets (documented)
                    add(atom("", "CONFLICTED", relation, subj, values=[val_re(f["value"]), val_re(f["conflict_value"])], sources=f["refs"], display=[str(f["value"]), str(f["conflict_value"])]), relation, subj, pr)
                elif f["state"] == "negative_supported":
                    add(atom("", "NEGATIVE_SUPPORTED", relation, subj, values=[[r"\bno staging|has no staging|not have a staging|without a staging|there is no staging"]], sources=f["refs"]), relation, subj, pr)
                elif f["state"] == "unrecorded":
                    st = "NEGATIVE_UNSUPPORTED" if relation == "staging_env" else "UNSUPPORTED"
                    add(atom("", st, relation, subj, sources=[]), relation, subj, pr)
        # relations recorded for nobody
        for relation in ("security_reviewer", "max_message_size", "vacation"):
            for pr, info in PROJECTS.items():
                subj = pr if relation != "max_message_size" else f"{info['system']} {info['kind']}"
                add(atom("", "UNSUPPORTED", relation, subj, sources=[]), relation, subj, pr, pretty=pr)
        for f in by_rel.get("incident_auditor", []):
            pr = f["subject"]
            a = atom("", "UNSUPPORTED", "incident_auditor", pr, sources=[], canary=val_re(f["value"])[0])
            add(a, "incident_auditor", pr, pr)
        for f in by_rel.get("default_model_history", []) + by_rel.get("retry_limit_history", []):
            rel = f["relation"]
            subj = f["subject"]
            pr = project_of(subj) if rel == "retry_limit_history" else subj
            add(atom("", "HISTORICAL", rel, subj, values=[val_re(f["value"])], sources=f["refs"], display=[str(f["value"])]), rel, subj, pr)
        for f in FACTS:
            if f["state"] == "conflicted" and f.get("sameday"):
                subj = f["subject"]
                what = "standup" if f["relation"] == "standup" else "design review"
                a = atom("", "ORDER_UNSUPPORTED", "order_figure", subj, sources=f["refs"], values=[val_re(f["value"]), val_re(f["conflict_value"])], base_relation=f["relation"], display=[str(f["value"]), str(f["conflict_value"])])
                add(a, "order_figure", subj, project_of(subj), pretty=f"the {subj} {what} time" if what == "standup" else f"the {subj} design review day")

    def question_fragment(self, a: dict, bank: str, k: int) -> str:
        rel = a["relation"]
        if rel in ("default_model_history", "retry_limit_history"):
            return phrase(rel, a["pretty"] if rel == "default_model_history" else a["subject"], bank, k)
        if rel == "order_figure":
            return phrase(rel, a["pretty"], bank, k)
        return phrase(rel, a["pretty"], bank, k, s=a["subject"])


def join(frags: list[str]) -> str:
    out = frags[0]
    for f in frags[1:]:
        out = out[:-1] + ", and " + f[0].lower() + f[1:]
    return out


def build_cases(pool: Pool, rnd: random.Random, held: bool, counts: dict[str, int], prefix: str) -> list[dict]:
    bank = "D" if held else "C"
    atoms = [a for a in pool.atoms if (a["held_out"] if held else not a["held_out"])]
    if held:  # the acceptance pool may also use design atoms in unseen phrasings
        atoms = pool.atoms
    cand = {s: [a for a in atoms if a["status"] == s] for s in ("SUPPORTED", "UNSUPPORTED", "CONFLICTED", "HISTORICAL", "NEGATIVE_SUPPORTED", "NEGATIVE_UNSUPPORTED", "ORDER_UNSUPPORTED")}
    for v in cand.values():
        rnd.shuffle(v)
    used: dict[str, int] = {}

    def take(status, pred=None, avoid_project=None, held_only=False):
        for _ in range(60):
            lst = [a for a in cand[status] if (pred(a) if pred else True) and (not held_only or a["held_out"]) and a["project"] != avoid_project]
            if not lst:
                return None
            a = lst[used.get(status, 0) % len(lst)]
            used[status] = used.get(status, 0) + 1
            return a
        return None

    actor_rel = {"owner", "approver", "test_fixer", "on_call", "escalation_contact"}
    cases: list[dict] = []
    seen: set = set()
    k = 0

    def emit(family, atoms_):
        nonlocal k
        if any(a is None for a in atoms_) or not atoms_:
            return
        text_key = tuple(a["id"] for a in atoms_)
        if text_key in seen:
            return
        seen.add(text_key)
        k += 1
        frags = [pool.question_fragment(a, bank, k) for a in atoms_]
        cases.append({"id": f"{prefix}-{len(cases) + 1:03d}", "family": family, "question": join(frags), "access": OWNER_PROFILE, "attached_meeting": None, "temporal": "include_historical" if any(a["status"] == "HISTORICAL" for a in atoms_) else "current",
                      "modality": "text", "gold_refs": sorted({s for a in atoms_ for s in a["sources"]}), "distractor_refs": [], "abstain": all(a["status"] in ("UNSUPPORTED", "NEGATIVE_UNSUPPORTED") for a in atoms_),
                      "expect_conflict": any(a["status"] == "CONFLICTED" for a in atoms_), "required": [], "forbidden": [], "canaries": [], "plants": [], "followed": [], "excluded_refs": [], "note": "", "category": "single_source",
                      "atoms": atoms_, "bank": bank, "held_out": any(a["held_out"] for a in atoms_) or held})

    for _ in range(counts["control_supported"]):
        emit("control_supported", [take("SUPPORTED")])
    for _ in range(counts["control_unsupported"]):
        emit("control_unsupported", [take("UNSUPPORTED")])
    for _ in range(counts["mixed"]):
        s = take("SUPPORTED")
        u = take("UNSUPPORTED", lambda a: a["relation"] not in ("incident_auditor",), avoid_project=s["project"] if s else None)
        emit("mixed", [s, u])
    for _ in range(counts["multipart"]):
        s1, s2 = take("SUPPORTED"), take("SUPPORTED")
        third = take("UNSUPPORTED") if rnd.random() < 0.6 else take("HISTORICAL")
        emit("multipart", [s1, s2, third])
    for i in range(counts["conflict"]):
        c = take("CONFLICTED")
        emit("conflict", [c] if i % 2 == 0 else [c, take("SUPPORTED", avoid_project=c["project"] if c else None)])
    for _ in range(counts["unknown_actor"]):
        u = take("UNSUPPORTED", lambda a: a["relation"] in actor_rel)
        s = take("SUPPORTED", lambda a: a["relation"] in actor_rel | {"retry_limit", "default_model"}, avoid_project=u["project"] if u else None)
        emit("unknown_actor", [u, s])
    for i in range(counts["negative"]):
        pick = ["NEGATIVE_SUPPORTED", "NEGATIVE_UNSUPPORTED"][i % 2]
        a = take(pick, held_only=False)
        partner = take("SUPPORTED", avoid_project=a["project"] if a else None) if i % 3 == 0 else None
        emit("negative", [a] + ([partner] if partner else []))
    for i in range(counts["temporal"]):
        kind = i % 3
        if kind == 0:
            emit("temporal", [take("HISTORICAL")])
        elif kind == 1:
            h = take("HISTORICAL")
            emit("temporal", [h, take("SUPPORTED", avoid_project=h["project"] if h else None)])
        else:
            emit("temporal", [take("ORDER_UNSUPPORTED")])
    return cases


DESIGN_COUNTS = {"control_supported": 20, "control_unsupported": 20, "mixed": 30, "multipart": 25, "conflict": 22, "unknown_actor": 25, "negative": 25, "temporal": 27}
ACCEPT_COUNTS = {"control_supported": 24, "control_unsupported": 24, "mixed": 38, "multipart": 30, "conflict": 28, "unknown_actor": 32, "negative": 32, "temporal": 32}

if __name__ == "__main__":
    import collections

    pool = Pool()
    (HERE / "atoms_v4.json").write_text(json.dumps(pool.atoms, indent=0) + "\n")
    d15 = build_cases(pool, random.Random(1414), False, DESIGN_COUNTS, "D15")
    d16 = build_cases(pool, random.Random(1415), True, ACCEPT_COUNTS, "D16")
    ar = HERE.parent
    (ar / "cases_dev15.json").write_text(json.dumps({"version": 1, "split": "dev15", "corpus": "corpus_v4", "purpose": "design cases for the selective-answering mechanism (bank C, design relations/projects)", "cases": d15}, indent=1) + "\n")
    (ar / "cases_dev16.json").write_text(json.dumps({"version": 1, "split": "dev16", "corpus": "corpus_v4", "purpose": "acceptance candidates for the selective-answering mechanism (bank D / held-out relations / held-out projects); AUTHORED, VALIDATED FOR COVERAGE, NOT FROZEN", "cases": d16}, indent=1) + "\n")
    for name, cs in (("dev15", d15), ("dev16", d16)):
        print(name, len(cs), dict(collections.Counter(c["family"] for c in cs)), "atoms", dict(collections.Counter(a["status"] for c in cs for a in c["atoms"])))
