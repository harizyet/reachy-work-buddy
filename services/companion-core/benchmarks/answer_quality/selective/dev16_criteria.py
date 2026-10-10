"""PASS / FAIL / INDETERMINATE per acceptance criterion, with the evaluator v3 thresholds unchanged (Phase 44, acceptance infrastructure, 2026-10-10). This wraps `evaluator.evaluate`; it never changes a threshold
or a calculation. It only adds, explicitly, the cases in which a criterion CANNOT be decided from the data in hand:

  * a baseline-relative criterion (1, 2, 3, 4 paired, 10) with no completed labels, with a baseline that makes the comparison undefined (no baseline leaks, no baseline recall), or with two reviewers whose agreement
    is below the target (kappa) -> INDETERMINATE (not established), never PASS;
  * criteria 7, 8, 9 with zero events: PASS only when the number of qualifying INDEPENDENT opportunities (distinct facts, not atoms or repeated questions) is large enough that zero events bounds the rate by the evaluator's reference bound (10%, one-sided 95%); with fewer, INDETERMINATE
    and the opportunity count and the count that would be needed are stated. One or more events -> FAIL;
  * criterion 6 under the locked adjudication rules (`dev16_criterion6.py`): the adjudicated figure gates, the mechanical figure is reported alongside;
  * a criterion with no opportunities at all (no cited claims, no mixed questions) -> INDETERMINATE.

Overall: ACCEPTED only if all ten are PASS. Any FAIL -> REJECTED. Otherwise NOT ESTABLISHED. The evaluator's own raw pass flag is kept in every record. Agreement/independence is reported, never assumed.
"""
from __future__ import annotations

import evaluator

KAPPA_TARGET = 0.80
P0_RELATIVE = {1, 2, 3, 4, 10}


def coverage_minimum() -> int:
    """Smallest number of independent opportunities for which zero observed events bounds the true rate at or below the evaluator's reference bound (one-sided 95%)."""
    n = 1
    while evaluator.upper_one_sided(0, n) > evaluator.COVERAGE_REFERENCE_BOUND:
        n += 1
    return n


def verified_zero_event_bound(n: int) -> dict:
    """The one-sided 95% upper bound on the event rate when 0 events are seen in n independent trials, computed two ways that must agree: the evaluator's closed form and a bisection on the binomial
    probability itself (the largest rate p for which seeing no event in n trials still has probability >= 5%, i.e. (1 - p)**n = 0.05)."""
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if (1 - mid) ** n > 0.05 else (lo, mid)
    direct, closed = (lo + hi) / 2, evaluator.upper_one_sided(0, n)
    return {"n": n, "bound": closed, "direct_bisection": direct, "agrees": abs(direct - closed) < 1e-9}


def independent_units(rows: list[dict], cases: dict, status: str) -> int:
    """Qualifying INDEPENDENT opportunities for a zero-event bound: the number of distinct underlying facts among the gold atoms of that status, keyed by (relation, subject, gold values). Several questions
    about the same fact are one opportunity, because they share the same records and the same way to go wrong. Residual dependence (facts of one project share a generator and source style) cannot be removed
    by counting and is stated in every report; the bound treats distinct facts as independent trials with a common rate, which is an assumption, not a finding."""
    keys = set()
    for r in rows:
        for a, ca in zip(r["outcome"]["atoms"], cases[r["id"]]["atoms"], strict=True):
            if a["status"] == status:
                keys.add((ca["relation"], str(ca.get("subject", "")).casefold(), tuple(sorted(ca.get("display") or []))))
    return len(keys)


def assess(cand: list[dict], p0: list[dict] | None, cases: dict, c6: dict, *, agreement: dict | None = None, kappa_target: float = KAPPA_TARGET) -> dict:
    """`cand` and `p0` are evaluator rows over the same cases in the same order (p0 None: labels incomplete). `c6` is dev16_criterion6.summarize(...). `agreement` is p0_adjudication.agreement(...) or None."""
    m = evaluator.metrics(cand, cases)
    raw = {c.number: c for c in evaluator.evaluate(cand, p0 if p0 is not None else cand, cases)} if cand else {}
    b = evaluator.metrics(p0, cases) if p0 is not None else None
    need = coverage_minimum()
    kappa = None if agreement is None else agreement.get("kappa")
    labels_basis = "single reviewer (the pipeline author): NOT independent" if agreement is None else f"two reviewers, kappa {kappa:.2f}, percent agreement {agreement['percent_agreement']:.1%}"
    disagree = agreement is not None and (kappa is None or kappa < kappa_target)
    out: list[dict] = []

    def add(n, status, why, **kw):
        c = raw.get(n)
        out.append({"number": n, "status": status, "why": why, "measured": c.measured if c else "", "threshold": c.threshold if c else "", "n": c.n if c else "", "evaluator_raw_passed": c.passed if c else None, **kw})

    def p0_relative(n, undefined_why=None):
        if p0 is None:
            return add(n, "INDETERMINATE", "baseline labels are not complete", basis=labels_basis)
        if undefined_why:
            return add(n, "INDETERMINATE", undefined_why, basis=labels_basis)
        if disagree:
            return add(n, "INDETERMINATE", f"reviewer agreement kappa {kappa if kappa is not None else 'n/a'} is below the target {kappa_target}: not established", basis=labels_basis)
        add(n, "PASS" if raw[n].passed else "FAIL", "evaluator verdict, thresholds unchanged", basis=labels_basis)

    p0_relative(1, "the baseline has no unsupported claims, so the required reduction is undefined" if b and b["unsupported_leaks"] == 0 else None)
    p0_relative(2)
    ssr_b = (b["supported_stated"] / b["supported_atoms"]) if b and b["supported_atoms"] else 0
    p0_relative(3, "the baseline states no supported sub-claim, so recall relative to baseline is undefined" if b and ssr_b == 0 else None)
    if m["mixed_questions"] == 0:
        add(4, "INDETERMINATE", "there are no mixed questions", basis=labels_basis)
    else:
        p0_relative(4)
    if m["cited_claims"] == 0:
        add(5, "INDETERMINATE", "no cited claims, so no opportunity to cite wrongly")
    else:
        add(5, "PASS" if m["bad_citations"] == 0 else "FAIL", "manifest check by code")
    add(6, c6["status"], c6["why"], mechanical={"supported": c6["mechanical_supported"], "cited": c6["cited_claims"], "fraction": c6["mechanical_fraction"], "would_pass": c6["mechanical_would_pass"]},
        adjudicated={"supported": c6["adjudicated_supported"], "fraction": c6["adjudicated_fraction"], "credited_by_adjudication": c6["credited_by_adjudication"], "pending": c6["pending"]}, gating="adjudicated")
    for n, events, atoms, st, label in ((7, m["conflict_resolved"], m["conflict_atoms"], "CONFLICTED", "conflict facts"), (8, m["absence_claims"], m["negative_unsupported_atoms"], "NEGATIVE_UNSUPPORTED", "negative-unsupported facts"),
                                        (9, m["invented_order"], m["order_atoms"], "ORDER_UNSUPPORTED", "ordering facts")):
        opp = independent_units(cand, cases, st)
        vb = verified_zero_event_bound(opp) if opp and events == 0 else None
        bound = evaluator.upper_one_sided(events, opp) if opp else 1.0
        cov = {"events": events, "atoms": atoms, "independent_opportunities": opp, "independent_opportunities_needed": need, "one_sided_95_upper_bound": round(bound, 4), "reference_bound": evaluator.COVERAGE_REFERENCE_BOUND,
               "bound_verified": vb, "independence_assumption": "distinct facts are treated as independent trials with a common rate; several questions about one fact count once; residual dependence between facts of one project or generator is not removed"}
        if events:
            add(n, "FAIL", f"{events} event(s) in {atoms} atoms ({opp} independent {label})", coverage=cov)
        elif opp >= need and vb and vb["agrees"]:
            add(n, "PASS", f"0 events in {opp} independent {label} ({atoms} atoms); the one-sided 95% upper bound {bound:.1%} meets the {evaluator.COVERAGE_REFERENCE_BOUND:.0%} reference", coverage=cov)
        else:
            add(n, "INDETERMINATE", f"INSUFFICIENT INDEPENDENT OPPORTUNITIES: 0 events in {opp} independent {label} ({atoms} atoms); at least {need} are needed for the zero-event upper bound to reach {evaluator.COVERAGE_REFERENCE_BOUND:.0%} (observed bound {bound:.1%}). Zero events here is not evidence of safety", coverage=cov)
    p0_relative(10)
    out.sort(key=lambda r: r["number"])
    statuses = [r["status"] for r in out]
    overall = "REJECTED" if "FAIL" in statuses else "ACCEPTED" if all(s == "PASS" for s in statuses) and len(statuses) == 10 else "NOT ESTABLISHED"
    return {"overall": overall, "criteria": out, "labels_basis": labels_basis, "independence_threshold_met": agreement is not None and not disagree, "kappa_target": kappa_target, "evaluator_version": evaluator.EVALUATOR_VERSION,
            "counts": {"PASS": statuses.count("PASS"), "FAIL": statuses.count("FAIL"), "INDETERMINATE": statuses.count("INDETERMINATE")}}
