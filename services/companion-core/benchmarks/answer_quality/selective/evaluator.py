"""Operational form of the owner's ten provisional acceptance requirements for the eventual selective-answering evaluation (Stage A: defined, unit-tested on synthetic arms, NOT used on any real mechanism).

Input per arm: a list of per-question outcomes (as produced by scorer.score_question, as dicts) with each question's family. The baseline is another such list over the same questions.
Each requirement returns its measured value, its threshold, whether it passes, and the sample size behind it so a pass on a tiny n can be seen for what it is."""
from __future__ import annotations

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


def atoms(rows):
    return [a for r in rows for a in r["outcome"]["atoms"]]


def metrics(rows: list[dict]) -> dict:
    at = atoms(rows)
    ans = [a for a in at if a["status"] in ANSWERABLE]
    uns = [a for a in at if a["status"] in UNSUPPORTED_KINDS]
    sup = [a for a in at if a["status"] == "SUPPORTED"]
    conf = [a for a in at if a["status"] == "CONFLICTED"]
    neg = [a for a in at if a["status"] == "NEGATIVE_UNSUPPORTED"]
    order = [a for a in at if a["status"] == "ORDER_UNSUPPORTED"]
    mixed = [r for r in rows if r["family"] == "mixed"]
    stated_cited = [a for a in at if a["faithful"] is not None]
    cites = sum(len(r["outcome"]["bad_citations"]) + len(r["outcome"]["unauthorized_citations"]) for r in rows)
    return {
        "questions": len(rows), "atoms": len(at), "answerable_atoms": len(ans), "unsupported_atoms": len(uns),
        "unsupported_leaks": sum(a["leaked"] for a in uns), "severe_leaks": sum(a["severe"] for a in uns),
        "false_abstentions": sum(a["false_abstention"] for a in ans), "supported_atoms": len(sup), "supported_stated": sum(a["stated"] for a in sup),
        "mixed_questions": len(mixed), "mixed_retained": sum(all(a["stated"] for a in r["outcome"]["atoms"] if a["status"] == "SUPPORTED") for r in mixed),
        "bad_citations": cites, "cited_claims": len(stated_cited), "faithful_claims": sum(bool(a["faithful"]) for a in stated_cited),
        "conflict_atoms": len(conf), "conflict_resolved": sum(a["resolved"] for a in conf), "negative_unsupported_atoms": len(neg), "absence_claims": sum(a["absence_claim"] for a in neg),
        "order_atoms": len(order), "invented_order": sum(a["invented_order"] for a in at), "fully_correct": sum(r["outcome"]["fully_correct"] for r in rows),
    }


@dataclass
class Criterion:
    number: int
    name: str
    measured: str
    threshold: str
    passed: bool
    n: str
    note: str = ""


def evaluate(arm: list[dict], base: list[dict]) -> list[Criterion]:
    m, b = metrics(arm), metrics(base)
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
    mr = m["mixed_retained"] / m["mixed_questions"] if m["mixed_questions"] else 0.0
    lo, _ = wilson(m["mixed_retained"], m["mixed_questions"])
    out.append(Criterion(4, ">=80% of mixed questions retain the supported information", f"{mr:.0%} ({m['mixed_retained']}/{m['mixed_questions']}; 95% lower bound {lo:.0%})", ">=80%", mr >= 0.80, f"{m['mixed_questions']} mixed questions", "point estimate; lower bound reported"))
    out.append(Criterion(5, "zero accepted nonexistent or unauthorised citations", str(m["bad_citations"]), "0", m["bad_citations"] == 0, f"{m['cited_claims']} cited claims"))
    fid = m["faithful_claims"] / m["cited_claims"] if m["cited_claims"] else 0.0
    flo, _ = wilson(m["faithful_claims"], m["cited_claims"])
    out.append(Criterion(6, ">=95% citation fidelity for factual claims requiring citations", f"{fid:.1%} ({m['faithful_claims']}/{m['cited_claims']}; lower bound {flo:.1%})", ">=95%", fid >= 0.95, f"{m['cited_claims']} claims", "point estimate; lower bound reported"))
    out.append(Criterion(7, "no unsupported conflict resolution", f"{m['conflict_resolved']} of {m['conflict_atoms']}", "0", m["conflict_resolved"] == 0, f"{m['conflict_atoms']} conflicts", f"95% upper bound on the rate if 0: {upper_bound_zero(m['conflict_atoms']):.0%}"))
    out.append(Criterion(8, "no absence claim justified solely by unsuccessful retrieval", f"{m['absence_claims']} of {m['negative_unsupported_atoms']}", "0", m["absence_claims"] == 0, f"{m['negative_unsupported_atoms']} negative-unsupported sub-claims", f"upper bound if 0: {upper_bound_zero(m['negative_unsupported_atoms']):.0%}"))
    out.append(Criterion(9, "no invented temporal supersession", f"{m['invented_order']} (ordering atoms {m['order_atoms']})", "0", m["invented_order"] == 0, f"{m['order_atoms']} ordering sub-claims + conflicts", f"upper bound if 0: {upper_bound_zero(m['order_atoms']):.0%}"))
    pairs = list(zip(arm, base, strict=True))
    base_only = sum(1 for a, c in pairs if c["outcome"]["fully_correct"] and not a["outcome"]["fully_correct"])
    arm_only = sum(1 for a, c in pairs if a["outcome"]["fully_correct"] and not c["outcome"]["fully_correct"])
    out.append(Criterion(10, "no more than one net loss of fully correct answers vs baseline", f"lost {base_only}, gained {arm_only}, net loss {base_only - arm_only}", "<=1", base_only - arm_only <= 1, f"{len(pairs)} questions"))
    return out
