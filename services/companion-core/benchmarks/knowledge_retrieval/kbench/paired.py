"""Paired, case-level comparison of two scored reports (same cases, same fixtures): wins, losses and ties per case, the mean difference
with a seeded bootstrap interval, an exact sign test, and an exact McNemar test on "every expected source in the top 5". With a few dozen
cases these say how much a difference could be chance; they do not make a small corpus a large one."""

from __future__ import annotations

import math
import random
from typing import Any

SEED = 44
RESAMPLES = 10000


def sign_test_p(wins: int, losses: int) -> float | None:
    """Exact two-sided sign test on the non-tied cases: the chance of a split at least this lopsided if wins and losses were equally likely."""
    n = wins + losses
    if n == 0:
        return None
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def bootstrap_ci(deltas: list[float], *, seed: int = SEED, resamples: int = RESAMPLES) -> tuple[float, float] | None:
    if not deltas:
        return None
    rng = random.Random(seed)
    n = len(deltas)
    means = sorted(sum(deltas[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def paired(a: dict[str, Any], b: dict[str, Any], metric: str = "recall@5") -> dict[str, Any]:
    """`b` minus `a`, over the cases that expect something and appear in both reports."""
    rows_a = {r["id"]: r for r in a["cases"]}
    rows_b = {r["id"]: r for r in b["cases"]}
    if a["fixtures"]["combined"] != b["fixtures"]["combined"]:
        raise ValueError("the two reports are not from the same fixtures")
    ids = [i for i in rows_a if i in rows_b and rows_a[i]["metrics"]["expected_count"]]
    deltas, wins, losses, ties, by_category = [], 0, 0, 0, {}
    for i in ids:
        d = rows_b[i]["metrics"][metric] - rows_a[i]["metrics"][metric]
        deltas.append(d)
        cat = by_category.setdefault(rows_a[i]["category"], {"b_better": 0, "a_better": 0, "tied": 0})
        if d > 1e-9:
            wins += 1
            cat["b_better"] += 1
        elif d < -1e-9:
            losses += 1
            cat["a_better"] += 1
        else:
            ties += 1
            cat["tied"] += 1
    only_b = sum(1 for i in ids if rows_b[i]["metrics"]["full_recall@5"] and not rows_a[i]["metrics"]["full_recall@5"])
    only_a = sum(1 for i in ids if rows_a[i]["metrics"]["full_recall@5"] and not rows_b[i]["metrics"]["full_recall@5"])
    rr = [rows_b[i]["metrics"]["rr"] - rows_a[i]["metrics"]["rr"] for i in ids]
    ci = bootstrap_ci(deltas)
    rr_ci = bootstrap_ci(rr)
    return {
        "a": a["adapter"]["name"], "b": b["adapter"]["name"], "metric": metric, "cases": len(ids),
        "mean_difference": round(sum(deltas) / len(deltas), 4) if deltas else None,
        "bootstrap95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
        "b_better": wins, "a_better": losses, "tied": ties, "sign_test_p": round(sign_test_p(wins, losses), 4) if sign_test_p(wins, losses) is not None else None,
        "mrr_mean_difference": round(sum(rr) / len(rr), 4) if rr else None, "mrr_bootstrap95": [round(rr_ci[0], 4), round(rr_ci[1], 4)] if rr_ci else None,
        "full_recall_at_5": {"only_b": only_b, "only_a": only_a, "mcnemar_exact_p": round(sign_test_p(only_b, only_a), 4) if sign_test_p(only_b, only_a) is not None else None},
        "by_category": by_category,
        "cases_where_b_better": [i for i, d in zip(ids, deltas, strict=True) if d > 1e-9],
        "cases_where_a_better": [i for i, d in zip(ids, deltas, strict=True) if d < -1e-9],
    }
