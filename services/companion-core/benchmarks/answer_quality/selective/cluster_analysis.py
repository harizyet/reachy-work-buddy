"""Cluster-aware (world-level) sensitivity analysis for the scorer-v3 validation: pre-registered, research-only, not run on any scorer output yet. The primary gate statistic treats each independent underlying fact as
one opportunity (exact binomial). Facts inside one world share project names, relations, people and templates, so a conservative companion analysis is reported beside it, for each population and category:

  world_level   a world with at least one event counts as a success only if EVERY event in it was detected; exact one-sided lower bound on the share of such worlds
  bootstrap     resample WORLDS with replacement (default 10,000 draws, fixed seed), recompute sensitivity, report the 5th percentile
  design_effect effective n = n / (1 + (m - 1) * icc) with m the mean events per world and icc the one-way ANOVA estimate; exact bound at the effective counts
The reported conservative bound is the MINIMUM of the bootstrap and design-effect bounds (the world-level share, which needs every event in a world detected, is a stress diagnostic reported beside them, not part of the minimum); the gate is judged on the primary statistic and the report states whether it also holds under the conservative one."""
from __future__ import annotations

import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import validation_analyze as va


def world_level(events: dict[int, tuple[int, int]]) -> dict:
    """events: world -> (detected, total events). Share of worlds (with events) in which every event was detected."""
    with_events = {w: v for w, v in events.items() if v[1] > 0}
    ok = sum(1 for d, t in with_events.values() if d == t)
    n = len(with_events)
    return {"worlds_with_events": n, "worlds_fully_detected": ok, "one_sided_95_lower": round(va.lower_bound(ok, n, 0.05), 4) if n else None}


def bootstrap(events: dict[int, tuple[int, int]], draws: int = 10000, seed: int = 20261015) -> dict:
    worlds = [v for v in events.values() if v[1] > 0]
    if not worlds:
        return {"fifth_percentile": None, "draws": 0}
    rnd = random.Random(seed)
    stats = []
    for _ in range(draws):
        pick = [worlds[rnd.randrange(len(worlds))] for _ in worlds]
        d, t = sum(x[0] for x in pick), sum(x[1] for x in pick)
        stats.append(d / t)
    stats.sort()
    return {"fifth_percentile": round(stats[int(0.05 * draws)], 4), "draws": draws}


def design_effect(events: dict[int, tuple[int, int]]) -> dict:
    """One-way ANOVA ICC on per-event detection (1 = detected) with worlds as clusters; effective counts; exact bound at the effective counts."""
    clusters = [(d, t) for d, t in events.values() if t > 0]
    n = sum(t for _, t in clusters)
    k = len(clusters)
    if k < 2 or n <= k:
        return {"icc": None, "effective_n": n, "one_sided_95_lower": None}
    grand = sum(d for d, _ in clusters) / n
    ssb = sum(t * (d / t - grand) ** 2 for d, t in clusters)
    ssw = sum(d * (1 - d / t) ** 2 + (t - d) * (d / t) ** 2 for d, t in clusters)
    msb, msw = ssb / (k - 1), ssw / (n - k)
    m = (n - sum(t * t for _, t in clusters) / n) / (k - 1)
    icc = max(0.0, (msb - msw) / (msb + (m - 1) * msw)) if (msb + (m - 1) * msw) > 0 else 0.0
    deff = 1 + (n / k - 1) * icc
    n_eff = n / deff
    detected = sum(d for d, _ in clusters)
    k_eff = round(detected / deff)
    return {"icc": round(icc, 4), "design_effect": round(deff, 3), "effective_n": round(n_eff, 1), "one_sided_95_lower": round(va.lower_bound(min(k_eff, round(n_eff)), max(1, round(n_eff)), 0.05), 4)}


def analyse(events: dict[int, tuple[int, int]]) -> dict:
    primary_d = sum(d for d, _ in events.values())
    primary_n = sum(t for _, t in events.values())
    a, b, c = world_level(events), bootstrap(events), design_effect(events)
    bounds = [x for x in (b["fifth_percentile"], c["one_sided_95_lower"]) if x is not None]  # the world-level share is a stress diagnostic, not part of the minimum
    return {"primary_exact_one_sided_95_lower": round(va.lower_bound(primary_d, primary_n, 0.05), 4) if primary_n else None, "events": primary_n, "detected": primary_d,
            "world_level": a, "bootstrap": b, "design_effect": c, "conservative_lower_bound": min(bounds) if bounds else None}
