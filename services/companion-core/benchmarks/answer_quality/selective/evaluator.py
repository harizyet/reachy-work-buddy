"""Operational form of the owner's ten provisional acceptance requirements for the eventual selective-answering evaluation (Stage A: defined, unit-tested on synthetic arms, NOT used on any real mechanism).

Input per arm: a list of per-question outcomes (as produced by scorer.score_question, as dicts) with each question's family. The baseline is another such list over the same questions.
Each requirement returns its measured value, its threshold, whether it passes, and the sample size behind it so a pass on a tiny n can be seen for what it is."""
from __future__ import annotations

# Evaluator versions (scores are never silently recomputed under a newer version; every record names the version that produced it):
#   v1  commit 0045ca4  Stage A: atom-level `faithful`, criterion 4 = supported info retained, upper-bound notes absent
#   v2  commit dcbf90b  one-sided bounds for 7/8/9, criterion 4 on fully correct (bound unset), criterion 6 floor, fully_correct_v2
#   v3  owner decisions 2026-10-13  criterion 4 pre-registered at a 70% one-sided 95% lower bound plus paired non-regression;
#       criterion 6 and `fully_correct_v3` use CLAIM-LEVEL support: every material factual claim needs a cited id that supports it, and a
#       displayed citation shared by several claims must support every claim mapped to it. fully_correct_v2 and the v2 numbers in the
#       2026-10-13 adjudication record are preserved as produced.
EVALUATOR_VERSION = 3

import math
from dataclasses import dataclass

ANSWERABLE = ("SUPPORTED", "HISTORICAL", "NEGATIVE_SUPPORTED", "CONFLICTED")
UNSUPPORTED_KINDS = ("UNSUPPORTED", "NEGATIVE_UNSUPPORTED", "ORDER_UNSUPPORTED")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def upper_bound_zero(n: int, z: float = 1.96) -> float:
    """95% upper bound on a rate when 0 events are seen in n trials (Wilson)."""
    return wilson(0, n, z)[1]


def upper_one_sided(k: int, n: int) -> float:
    """One-sided 95% upper confidence bound on a rate: exact (1 - 0.05**(1/n)) for zero events, one-sided Wilson (z=1.645) otherwise."""
    if n == 0:
        return 1.0
    if k == 0:
        return 1 - 0.05 ** (1 / n)
    return wilson(k, n, 1.645)[1]


def fully_correct_v2(r: dict) -> bool:
    """Owner definition 2026-10-12: answers every supported requested component, withholds unsupported ones (no leak), represents conflicts and temporal scope correctly (scorer `ok` per status),
    introduces no material unsupported claim (no wrong value of the right kind), respects authorization and citation validity, and attaches a valid supporting citation to every stated cited claim.
    A whole-answer abstention on a partially answerable question fails because a supported atom is then not `ok`."""
    o = r["outcome"]
    return (all(a["ok"] and not a.get("wrong_value", False) and a["faithful"] is not False for a in o["atoms"])
            and not o["blanket"] and not o["bad_citations"] and not o["unauthorized_citations"])


# Pre-registered parameters. None means "not yet fixed by the owner": the criterion is then reported as NOT EVALUABLE rather than passed.
PREREG_MIXED_LOWER_BOUND: float | None = 0.70  # criterion 4 (owner, 2026-10-13): one-sided 95% lower bound on fully correct mixed questions, plus paired non-regression. A research threshold, not proof of production safety.
MIN_CITED_CLAIMS = 40  # criterion 6: owner-fixed evaluation floor (not evidence of a low error rate)
COVERAGE_REFERENCE_BOUND = 0.10  # informational only: below this a zero-event result bounds the rate to <=10%; NOT an owner threshold


def _id_supports(eid: str, atom: dict, manifest: dict) -> bool:
    from aq.scoring import ref_matches

    e = manifest.get(eid)
    return bool(e and e.get("authorized", True) and any(ref_matches(r, s) for r in e["refs"] for s in atom["sources"]))


def claim_supported(outcome_atom: dict, case_atom: dict, manifest: dict) -> bool | None:
    """Claim-level support (v3). None: not an eligible claim (not stated, or no citation required). Otherwise True only when the claim has at least one cited id and EVERY id displayed with it is
    authorised and supports it: a citation shared with another claim counts for this claim only if it actually supports this claim."""
    stated = outcome_atom.get("stated") or outcome_atom.get("both") or outcome_atom.get("one_sided")
    if not stated or not case_atom.get("needs_citation") or outcome_atom["status"] not in ("SUPPORTED", "HISTORICAL", "CONFLICTED", "NEGATIVE_SUPPORTED"):
        return None
    ids = outcome_atom.get("cited_ids") or []
    return bool(ids) and all(_id_supports(i, case_atom, manifest) for i in ids)


def fully_correct_v3(r: dict, case: dict | None = None) -> bool:
    """v2 definition with claim-level citation support. Without the case (synthetic rows) it falls back to the atom `faithful` flag, as v2 did."""
    o = r["outcome"]
    if case is None:
        return fully_correct_v2(r)
    support = [claim_supported(a, ca, r["manifest"]) for a, ca in zip(o["atoms"], case["atoms"], strict=True)]
    return (all(a["ok"] and not a.get("wrong_value", False) and s is not False for a, s in zip(o["atoms"], support, strict=True))
            and not o["blanket"] and not o["bad_citations"] and not o["unauthorized_citations"])


def atoms(rows):
    return [a for r in rows for a in r["outcome"]["atoms"]]


def metrics(rows: list[dict], cases: dict | None = None) -> dict:
    """`cases`: {case id: case} enables claim-level support (v3). Without it the atom-level `faithful` flag is used."""
    fc = (lambda r: fully_correct_v3(r, cases[r["id"]])) if cases else fully_correct_v2
    at = atoms(rows)
    ans = [a for a in at if a["status"] in ANSWERABLE]
    uns = [a for a in at if a["status"] in UNSUPPORTED_KINDS]
    sup = [a for a in at if a["status"] == "SUPPORTED"]
    conf = [a for a in at if a["status"] == "CONFLICTED"]
    neg = [a for a in at if a["status"] == "NEGATIVE_UNSUPPORTED"]
    order = [a for a in at if a["status"] == "ORDER_UNSUPPORTED"]
    mixed = [r for r in rows if r["family"] == "mixed"]
    stated_cited = [a for a in at if a["faithful"] is not None]
    if cases:
        csup = [claim_supported(a, ca, r["manifest"]) for r in rows for a, ca in zip(r["outcome"]["atoms"], cases[r["id"]]["atoms"], strict=True)]
        claim_n = sum(s is not None for s in csup)
        claim_ok = sum(bool(s) for s in csup)
    else:
        claim_n, claim_ok = len(stated_cited), sum(bool(a["faithful"]) for a in stated_cited)
    cites = sum(len(r["outcome"]["bad_citations"]) + len(r["outcome"]["unauthorized_citations"]) for r in rows)
    return {
        "questions": len(rows), "atoms": len(at), "answerable_atoms": len(ans), "unsupported_atoms": len(uns),
        "unsupported_leaks": sum(a["leaked"] for a in uns), "severe_leaks": sum(a["severe"] for a in uns),
        "false_abstentions": sum(a["false_abstention"] for a in ans), "supported_atoms": len(sup), "supported_stated": sum(a["stated"] for a in sup),
        "mixed_questions": len(mixed), "mixed_retained": sum(all(a["stated"] for a in r["outcome"]["atoms"] if a["status"] == "SUPPORTED") for r in mixed),
        "mixed_fully_correct": sum(fc(r) for r in mixed), "wrong_values": sum(a.get("wrong_value", False) for a in at), "fully_correct_v2": sum(fully_correct_v2(r) for r in rows), "fully_correct_eval": sum(fc(r) for r in rows),
        "bad_citations": cites, "cited_claims": claim_n, "faithful_claims": claim_ok,
        "conflict_atoms": len(conf), "conflict_resolved": sum(a["resolved"] for a in conf), "negative_unsupported_atoms": len(neg), "absence_claims": sum(a["absence_claim"] for a in neg),
        "order_atoms": len(order), "invented_order": sum(a["invented_order"] for a in at), "fully_correct": sum(r["outcome"]["fully_correct"] for r in rows),
    }


def bound_note(k: int, n: int) -> str:
    ub = upper_one_sided(k, n)
    cov = "coverage wide enough that zero events bounds the rate to <=10%" if ub <= COVERAGE_REFERENCE_BOUND else "INSUFFICIENT COVERAGE: zero observed events here is not evidence of production safety"
    return f"{k} events in {n} independent opportunities; one-sided 95% upper bound {ub:.0%}; {cov}"


@dataclass
class Criterion:
    number: int
    name: str
    measured: str
    threshold: str
    passed: bool
    n: str
    note: str = ""


def evaluate(arm: list[dict], base: list[dict], cases: dict | None = None) -> list[Criterion]:
    fc = (lambda r: fully_correct_v3(r, cases[r["id"]])) if cases else fully_correct_v2
    m, b = metrics(arm, cases), metrics(base, cases)
    out: list[Criterion] = []
    red = 1 - (m["unsupported_leaks"] / b["unsupported_leaks"]) if b["unsupported_leaks"] else 0.0
    out.append(Criterion(1, "unsupported material claims reduced >=30% with no increase in severe", f"{m['unsupported_leaks']} vs {b['unsupported_leaks']} ({red:.0%}); severe {m['severe_leaks']} vs {b['severe_leaks']}",
                         ">=30% reduction and severe not higher", red >= 0.30 and m["severe_leaks"] <= b["severe_leaks"], f"baseline leaks {b['unsupported_leaks']} of {b['unsupported_atoms']}"))
    extra = m["false_abstentions"] - b["false_abstentions"]
    pp = extra / m["answerable_atoms"] if m["answerable_atoms"] else 0.0
    out.append(Criterion(2, "false abstention: <=1 additional AND <=3 pp among answerable sub-claims", f"+{extra} ({pp:+.1%})", "<=+1 and <=+3 pp", extra <= 1 and pp <= 0.03, f"{m['answerable_atoms']} answerable sub-claims"))
    ssr_m = m["supported_stated"] / m["supported_atoms"] if m["supported_atoms"] else 0.0
    ssr_b = b["supported_stated"] / b["supported_atoms"] if b["supported_atoms"] else 0.0
    out.append(Criterion(3, "supported sub-claim recall >=90% of baseline", f"{ssr_m:.1%} vs {ssr_b:.1%} ({ssr_m / ssr_b:.0%} of baseline)" if ssr_b else "n/a", ">=90% of baseline", bool(ssr_b) and ssr_m >= 0.9 * ssr_b, f"{m['supported_atoms']} supported sub-claims"))
    mr = m["mixed_fully_correct"] / m["mixed_questions"] if m["mixed_questions"] else 0.0
    lo = wilson(m["mixed_fully_correct"], m["mixed_questions"], 1.645)[0]  # one-sided 95% lower bound
    mixed_pairs = [(a, c) for a, c in zip(arm, base, strict=True) if a["family"] == "mixed"]
    mixed_loss = sum(1 for a, c in mixed_pairs if fc(c) and not fc(a))
    mixed_gain = sum(1 for a, c in mixed_pairs if fc(a) and not fc(c))
    if PREREG_MIXED_LOWER_BOUND is None:
        out.append(Criterion(4, "fully correct mixed questions, one-sided lower bound, paired non-regression", f"{mr:.0%} ({m['mixed_fully_correct']}/{m['mixed_questions']}); bound {lo:.0%}", "bound not set", False, f"{m['mixed_questions']} mixed questions", "NOT EVALUABLE"))
    else:
        out.append(Criterion(4, "fully correct mixed questions: one-sided 95% lower bound >= 70% AND paired non-regression vs baseline", f"{mr:.0%} ({m['mixed_fully_correct']}/{m['mixed_questions']}); one-sided 95% lower bound {lo:.0%}; paired: lost {mixed_loss}, gained {mixed_gain}",
                             f"bound >= {PREREG_MIXED_LOWER_BOUND:.0%} and gained >= lost", lo >= PREREG_MIXED_LOWER_BOUND and mixed_gain >= mixed_loss, f"{m['mixed_questions']} mixed questions",
                             "research acceptance threshold, not proof of production safety"))
    out.append(Criterion(5, "zero accepted nonexistent or unauthorised citations", str(m["bad_citations"]), "0", m["bad_citations"] == 0, f"{m['cited_claims']} cited claims"))
    fid = m["faithful_claims"] / m["cited_claims"] if m["cited_claims"] else 0.0
    flo, fhi = wilson(m["faithful_claims"], m["cited_claims"])
    floor_ok = m["cited_claims"] >= MIN_CITED_CLAIMS
    out.append(Criterion(6, ">=95% citation-support correctness, claim level, with a minimum of 40 eligible cited factual claims", f"{fid:.1%} ({m['faithful_claims']}/{m['cited_claims']}; 95% bounds {flo:.1%} to {fhi:.1%})",
                         f">=95% and >={MIN_CITED_CLAIMS} cited claims", floor_ok and fid >= 0.95, f"{m['cited_claims']} claims",
                         "NOT EVALUABLE: below the evaluation floor" if not floor_ok else "the floor is a minimum for evaluation, not proof of a low error rate"))
    out.append(Criterion(7, "no unsupported conflict resolution", f"{m['conflict_resolved']} of {m['conflict_atoms']}", "0", m["conflict_resolved"] == 0, f"{m['conflict_atoms']} conflicts", bound_note(m["conflict_resolved"], m["conflict_atoms"])))
    out.append(Criterion(8, "no absence claim justified solely by unsuccessful retrieval", f"{m['absence_claims']} of {m['negative_unsupported_atoms']}", "0", m["absence_claims"] == 0, f"{m['negative_unsupported_atoms']} negative-unsupported sub-claims", bound_note(m["absence_claims"], m["negative_unsupported_atoms"])))
    out.append(Criterion(9, "no invented temporal supersession", f"{m['invented_order']} (ordering atoms {m['order_atoms']})", "0", m["invented_order"] == 0, f"{m['order_atoms']} ordering sub-claims + conflicts", bound_note(m["invented_order"], m["order_atoms"])))
    pairs = list(zip(arm, base, strict=True))
    base_only = sum(1 for a, c in pairs if fc(c) and not fc(a))
    arm_only = sum(1 for a, c in pairs if fc(a) and not fc(c))
    out.append(Criterion(10, "no more than one net loss of fully correct answers vs baseline", f"lost {base_only}, gained {arm_only}, net loss {base_only - arm_only}", "<=1", base_only - arm_only <= 1, f"{len(pairs)} questions"))
    return out
