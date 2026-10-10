"""Criterion 6 under the LOCKED adjudication rules (`dev16_criterion6_rules.json`; Phase 44, acceptance infrastructure, 2026-10-10). Pure functions, no model, no I/O except reading the rules file.

The evaluator's mechanical claim-level check (evaluator v3, unchanged) counts a cited claim as supported only when every cited id is an authorised registered source of the atom. A true claim that cites an authorised
record the case does not register therefore fails mechanically. This module lets two blinded reviewers judge ONLY whether the cited record's text supports the claim; code then derives the category from code facts:

    1  SUPPORTS + record in the evidence universe + not a registered source   -> eligible for credit (both reviewers, valid verbatim span)
    2  SUPPORTS but the record is NOT in the evidence universe                  -> never credited
    3  DOES_NOT_SUPPORT                                                         -> never credited

Reviewers never judge authorisation or scope (code facts) and are not told the mechanical verdict, the arm or which claims are controls. Nothing here edits a frozen result: it produces new data, and the mechanical
figure is reported next to the adjudicated one. The threshold and floor are the evaluator's (>= 95%, >= 40 cited claims) and are not changed.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Callable
from pathlib import Path

import evaluator

HERE = Path(__file__).resolve().parent
RULES_PATH = HERE / "dev16_criterion6_rules.json"


class RulesError(RuntimeError):
    pass


def rules_sha256() -> str:
    return hashlib.sha256(RULES_PATH.read_bytes()).hexdigest()


def load_rules(expected_sha256: str) -> dict:
    """Refuse to use rules that differ from the locked, manifest-hashed ones."""
    if rules_sha256() != expected_sha256:
        raise RulesError("criterion-6 rules differ from the locked manifest hash; refusing to adjudicate")
    return json.loads(RULES_PATH.read_text())


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def span_valid(span: str | None, record_text: str) -> bool:
    return bool(span and norm(span) and norm(span) in norm(record_text))


def cited_claims(rows: list[dict], cases: dict) -> list[dict]:
    """Every eligible cited claim of the candidate's rows, with the mechanical verdict per cited id."""
    out = []
    for r in rows:
        case = cases[r["id"]]
        for a, ca in zip(r["outcome"]["atoms"], case["atoms"], strict=True):
            sup = evaluator.claim_supported(a, ca, r["manifest"])
            if sup is None:
                continue
            ids = list(a.get("cited_ids") or [])
            out.append({"case_id": r["id"], "atom_id": ca["id"], "cited_ids": ids, "mechanical": bool(sup), "registered": {i: evaluator._id_supports(i, ca, r["manifest"]) for i in ids},
                        "reply": r["reply"], "question": r["question"], "gold": list(ca["display"]), "subject": ca.get("pretty") or ca["subject"]})
    return out


def claim_sentence(reply: str, ids: list[str]) -> str:
    lines = [ln for ln in reply.split("\n") if any(f"[{i}]" in ln for i in ids)]
    return " ".join(lines) or reply


def select_for_review(claims: list[dict], record_text: Callable[[str, str], str], *, seed: int, controls: int = 30) -> list[dict]:
    """The reviewed population: all mechanically unsupported claims, all claims whose cited record text does not contain the atom's subject (a code-detectable proxy for context-, title- or speaker-bound
    claims), and `controls` seeded mechanically supported claims. Returns each claim tagged with why it is in the packet (the tag never reaches a reviewer). The `not_direct_diagnostic` tag is a DIAGNOSTIC: a cited text without the subject's name is not evidence of incorrect or non-direct binding and decides nothing; it only sends the claim to a reviewer."""
    chosen, rest = [], []
    for c in claims:
        subj = norm(c["subject"])
        indirect = any(subj not in norm(record_text(c["case_id"], i)) for i in c["cited_ids"])
        if not c["mechanical"]:
            chosen.append({**c, "why": "mechanically_unsupported"})
        elif indirect:
            chosen.append({**c, "why": "not_direct_diagnostic"})
        else:
            rest.append(c)
    rnd = random.Random(seed)
    rnd.shuffle(rest)
    chosen += [{**c, "why": "control"} for c in rest[:controls]]
    return chosen


def oid(seed: int, case_id: str, atom_id: str) -> str:
    return "C" + hashlib.sha256(f"c6|{seed}|{case_id}|{atom_id}".encode()).hexdigest()[:8]


def universe_facts(case: dict, eid: str, manifest: dict, ref_violations: Callable[[str, dict], list[str]]) -> dict:
    """Code facts about one cited record. `ref_violations(ref, case)` is kbench.security.violations for the case's access profile (empty list: authorised and in scope)."""
    entry = manifest.get(eid)
    if entry is None:
        return {"in_manifest": False, "violations": ["not_in_manifest"], "excluded": False, "in_universe": False}
    reasons, excluded = [], False
    for ref in entry["refs"]:
        reasons += ref_violations(ref, case)
        excluded |= any(ref.split("#")[0] == x.split("#")[0] for x in case.get("excluded_refs") or [])
    if not entry.get("authorized", True):
        reasons.append("not_authorised")
    return {"in_manifest": True, "violations": sorted(set(reasons)), "excluded": excluded, "in_universe": not reasons and not excluded}


def build_packet(selected: list[dict], cases: dict, record_text: Callable[[str, str], str], facts: Callable[[dict, str], dict], *, seed: int, record_context: Callable[[str, str], str] | None = None) -> tuple[list[dict], dict]:
    """(items, key). Items carry no arm, no mechanical verdict and no reason for inclusion; the key maps opaque id to (case, atom, why) and is sealed away from reviewers."""
    items, key = [], {}
    order = sorted(selected, key=lambda c: oid(seed, c["case_id"], c["atom_id"]))
    random.Random(seed).shuffle(order)
    for c in order:
        o = oid(seed, c["case_id"], c["atom_id"])
        case = cases[c["case_id"]]
        items.append({"oid": o, "question": c["question"], "claim": claim_sentence(c["reply"], c["cited_ids"]), "gold": c["gold"],
                      "records": [{"eid": i, "text": record_text(c["case_id"], i), "context": (record_context(c["case_id"], i) if record_context else ""), "authorised_and_in_scope": facts(case, i)["in_universe"], "code_reasons": facts(case, i)["violations"]} for i in c["cited_ids"]]})
        key[o] = {"case_id": c["case_id"], "atom_id": c["atom_id"], "why": c["why"]}
    return items, key


def render_packet(items: list[dict], rules: dict) -> str:
    out = ["CRITERION-6 CITATION REVIEW (blinded). " + rules["reviewer_question"], "For each cited record answer SUPPORTS (with a verbatim span from that record), DOES_NOT_SUPPORT, or UNRESOLVABLE when the claim, the passage and the shown context do not settle it. Authorisation and scope are code facts; do not judge them.\n"]
    for it in items:
        out += [f"### {it['oid']}", f"QUESTION: {it['question']}", f"CLAIM: {it['claim']!r}", f"GOLD ANSWER: {' / '.join(it['gold']) or '(none)'}"]
        for r in it["records"]:
            out += [f"  - {r['eid']} (authorised and in scope: {'yes' if r['authorised_and_in_scope'] else 'NO ' + ','.join(r['code_reasons'])}){' [context: ' + r['context'] + ']' if r['context'] else ''}: {r['text']!r}"]
        out.append("")
    return "\n".join(out)


def template(items: list[dict]) -> dict:
    return {it["oid"]: {r["eid"]: {"answer": None, "span": ""} for r in it["records"]} for it in items}


def adjudicate(selected: list[dict], key: dict, cases: dict, answers_a: dict | None, answers_b: dict | None, record_text: Callable[[str, str], str], facts: Callable[[dict, str], dict], *, seed: int,
               record_context: Callable[[str, str], str] | None = None) -> list[dict]:
    """Per reviewed claim: credited / not_credited / pending, with the reason, per unregistered cited id. Registered supporting ids need no review. Uses only code facts and the reviewers' SUPPORTS answers."""
    out = []
    for c in selected:
        o = oid(seed, c["case_id"], c["atom_id"])
        case = cases[c["case_id"]]
        per_id, credited, pending, blocked, unresolved = {}, True, False, False, False
        for i in c["cited_ids"]:
            if c["registered"][i]:
                per_id[i] = {"category": "registered", "credited": True}
                continue
            f = facts(case, i)
            text = record_text(c["case_id"], i) + " " + (record_context(c["case_id"], i) if record_context else "")
            answers = []
            for ans in (answers_a, answers_b):
                x = (ans or {}).get(o, {}).get(i)
                answers.append(None if not x or not x.get("answer") else x)
            if any(a is None for a in answers):
                per_id[i] = {"category": "pending", "credited": False, "why": "a reviewer has not answered" if any(answers) or answers_a or answers_b else "no reviewer answered", "facts": f}
                pending = True
                continue
            valid = [a["answer"] == "SUPPORTS" and span_valid(a.get("span"), text) for a in answers]
            if any(a["answer"] == "UNRESOLVABLE" for a in answers):
                per_id[i] = {"category": "unresolved", "credited": False, "facts": f}
                unresolved = True
                continue
            if all(valid):
                cat = 1 if f["in_universe"] else 2
                per_id[i] = {"category": cat, "credited": cat == 1, "facts": f, "spans": [a["span"] for a in answers]}
            elif any(a["answer"] == "SUPPORTS" for a in answers) and not all(a["answer"] == "SUPPORTS" for a in answers):
                per_id[i] = {"category": "reviewers_disagree", "credited": False, "facts": f}
            elif any(a["answer"] == "SUPPORTS" for a in answers):
                per_id[i] = {"category": "void_span", "credited": False, "facts": f}
            else:
                per_id[i] = {"category": 3, "credited": False, "facts": f}
            if not per_id[i]["credited"]:
                blocked = True
        credited = all(v["credited"] for v in per_id.values())
        status = "credited" if credited else "not_credited" if blocked else "unresolved" if unresolved else "pending" if pending else "not_credited"
        out.append({"case_id": c["case_id"], "atom_id": c["atom_id"], "oid": o, "why_reviewed": key.get(o, {}).get("why", c.get("why")), "mechanical": c["mechanical"], "status": status, "ids": per_id})
    return out


def summarize(metrics: dict, adjudication: list[dict], rules: dict) -> dict:
    """The two figures and the status. `metrics` is evaluator.metrics(candidate rows, cases): cited_claims and faithful_claims are the mechanical numbers."""
    cited, faithful = metrics["cited_claims"], metrics["faithful_claims"]
    floor, thr = rules["threshold"]["min_cited_claims"], rules["threshold"]["min_fraction"]
    unsupported = [a for a in adjudication if not a["mechanical"]]
    credited = sum(a["status"] == "credited" for a in unsupported)
    pending = sum(a["status"] == "pending" for a in unsupported)
    unresolved = sum(a["status"] == "unresolved" for a in unsupported)
    not_reviewed = (cited - faithful) - len(unsupported)  # mechanically unsupported claims missing from the adjudication list altogether
    mech = faithful / cited if cited else 0.0
    adj = (faithful + credited) / cited if cited else 0.0
    best = (faithful + credited + pending + unresolved + max(not_reviewed, 0)) / cited if cited else 0.0
    if cited < floor:
        status, why = "INDETERMINATE", f"{cited} cited claims, below the evaluation floor of {floor}"
    elif adj >= thr:
        status, why = "PASS", "adjudicated figure meets the threshold"
    elif best < thr:
        status, why = "FAIL", "even crediting every still-pending or unresolved eligible claim would stay below the threshold"
    else:
        status, why = "INDETERMINATE", f"{pending + unresolved + max(not_reviewed, 0)} mechanically unsupported claims are still pending or unresolved ({unresolved} unresolved) and could change the verdict"
    return {"cited_claims": cited, "mechanical_supported": faithful, "mechanical_fraction": mech, "mechanical_would_pass": cited >= floor and mech >= thr, "credited_by_adjudication": credited, "pending": pending, "unresolved": unresolved,
            "adjudicated_supported": faithful + credited, "adjudicated_fraction": adj, "best_case_fraction": best, "threshold": thr, "floor": floor, "status": status, "why": why,
            "uncredited_reasons": {a["case_id"] + "/" + a["atom_id"]: {i: v["category"] for i, v in a["ids"].items() if not v["credited"]} for a in unsupported if a["status"] == "not_credited"}}
