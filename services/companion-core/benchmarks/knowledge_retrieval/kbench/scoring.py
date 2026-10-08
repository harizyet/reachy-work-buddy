"""Pure scoring functions. No stores, no I/O; every definition here is the one the report cites."""

from __future__ import annotations

import math
from collections.abc import Sequence


def parts(key: str) -> tuple[str, str, str | None]:
    source_type, _, rest = key.partition(":")
    source_id, _, locator = rest.partition("#")
    return source_type, source_id, (locator or None)


def matches(hit_key: str, expected_key: str) -> bool:
    """A hit satisfies an expected reference when it names the same source and, if the reference names a part (a segment or
    chunk), the same part. A reference without a part is satisfied by any part of that source."""
    ht, hi, hl = parts(hit_key)
    et, ei, el = parts(expected_key)
    return ht == et and hi == ei and (el is None or hl == el)


def same_source(a: str, b: str) -> bool:
    return parts(a)[:2] == parts(b)[:2]


def dedupe(keys: Sequence[str]) -> list[str]:
    """Rank order with repeats removed (the first, best-ranked occurrence of a key counts)."""
    seen: set[str] = set()
    return [k for k in keys if not (k in seen or seen.add(k))]


def found_in_top(keys: Sequence[str], expected: Sequence[str], k: int) -> list[str]:
    top = dedupe(keys)[:k]
    return [e for e in expected if any(matches(h, e) for h in top)]


def recall_at_k(keys: Sequence[str], expected: Sequence[str], k: int) -> float | None:
    if not expected:
        return None
    return len(found_in_top(keys, expected, k)) / len(expected)


def precision_at_k(keys: Sequence[str], expected: Sequence[str], k: int) -> float | None:
    """Relevant hits in the top k divided by the hits actually returned in the top k (0 when nothing was returned), so a
    system is not rewarded for returning fewer results nor punished for having fewer than k to return."""
    if not expected:
        return None
    top = dedupe(keys)[:k]
    if not top:
        return 0.0
    return sum(1 for h in top if any(matches(h, e) for e in expected)) / len(top)


def reciprocal_rank(keys: Sequence[str], expected: Sequence[str]) -> float | None:
    if not expected:
        return None
    for rank, hit in enumerate(dedupe(keys), start=1):
        if any(matches(hit, e) for e in expected):
            return 1.0 / rank
    return 0.0


def source_attribution_at_k(keys: Sequence[str], expected: Sequence[str], k: int) -> float | None:
    """Of the top-k hits, the share that come from a source the answer needs (the part is ignored)."""
    if not expected:
        return None
    top = dedupe(keys)[:k]
    if not top:
        return 0.0
    return sum(1 for h in top if any(same_source(h, e) for e in expected)) / len(top)


def citation_correctness_at_k(keys: Sequence[str], expected: Sequence[str], k: int) -> float | None:
    """Of the expected references that name a part, the share found with exactly that part in the top k."""
    named = [e for e in expected if parts(e)[2] is not None]
    if not named:
        return None
    return len(found_in_top(keys, named, k)) / len(named)


def temporal_correct(keys: Sequence[str], expected: Sequence[str], stale: Sequence[str], k: int = 5) -> bool | None:
    """The current fact is in the top k and no superseded one outranks it."""
    if not stale or not expected:
        return None
    ranked = dedupe(keys)
    best_expected = next((r for r, h in enumerate(ranked) if any(matches(h, e) for e in expected)), None)
    if best_expected is None or best_expected >= k:
        return False
    best_stale = next((r for r, h in enumerate(ranked) if any(matches(h, s) for s in stale)), None)
    return best_stale is None or best_stale > best_expected


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a proportion; None when there are no trials. Clustered data (pooled elements) understates
    the real uncertainty, which the report notes where it uses that."""
    if n <= 0:
        return None
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def percentile(values: Sequence[float], p: float) -> float | None:
    """Nearest-rank percentile (p in 0..100); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def mean(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None
