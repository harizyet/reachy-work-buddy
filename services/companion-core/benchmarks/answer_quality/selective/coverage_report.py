"""Corpus and set validation for the selective-answering work: (1) gold unambiguity checks (unique facts per subject and relation; no two relations whose question templates share distinctive content words;
every atom's status agrees with the registry); (2) coverage of the design and candidate-acceptance sets per family, status, severity and distinct atom; (3) whether each of the owner's ten provisional
requirements is operationally measurable with that coverage (the sample size behind it and the weakest bound it can support)."""
from __future__ import annotations

import collections
import itertools
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corpus_gen as gen
from banks import BANKS
from evaluator import upper_bound_zero, wilson

STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "is", "are", "was", "were", "be", "by", "with", "and", "or", "what", "who", "which", "when", "where", "how", "does", "do", "did", "it", "its", "that", "this", "from", "at", "as", "has", "have", "had", "will", "would", "can", "could", "many", "much", "long", "often", "there", "their", "they", "them", "one", "other"}
ALLOWED_SHARED = {"model", "default", "release", "planning", "team", "meeting", "failed", "job", "jobs", "day", "week", "weekday", "weekdays", "someone", "person", "people", "up", "out"}


def words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", t.lower().replace("{x}", " ").replace("{s}", " ")) if w not in STOP and len(w) > 2}


DISTINCTIVE = {"limit", "size", "retry", "retries", "rollback", "budget", "funded", "funding", "deadline", "approved", "approve", "approval", "staging", "newer", "vacation", "audit", "security", "escalate", "escalation", "release", "review", "owns", "lead", "leads", "hours", "model"}
TWINS = {frozenset(p) for p in (("retry_limit", "retry_limit_history"), ("default_model", "default_model_history"), ("default_model", "decision"), ("approver", "budget_through"), ("security_reviewer", "approver"))}


def template_overlaps() -> list[str]:
    """Pairs of relations whose question templates share content words that are not on the allowed list: a question about one could be answered with the other's value."""
    sig = {rel: set().union(*(words(t) for t in tpls)) for rel, tpls in BANKS.items()}
    issues = []
    for a, b in itertools.combinations(sig, 2):
        shared = ((sig[a] & sig[b]) - ALLOWED_SHARED) & DISTINCTIVE
        if shared and frozenset((a, b)) not in TWINS:
            issues.append(f"{a} / {b}: {sorted(shared)}")
    return issues


def registry_ambiguity() -> list[str]:
    return gen.check_unique(json.loads((HERE / "facts_v4.json").read_text()))


def coverage(path: Path):
    cases = json.loads(path.read_text())["cases"]
    fam = collections.Counter(c["family"] for c in cases)
    st = collections.Counter(a["status"] for c in cases for a in c["atoms"])
    distinct = {s: len({a["id"] for c in cases for a in c["atoms"] if a["status"] == s}) for s in st}
    severe = sum(a["severe"] for c in cases for a in c["atoms"])
    return cases, fam, st, distinct, severe


if __name__ == "__main__":
    print("registry ambiguity (duplicate facts):", registry_ambiguity() or "none")
    ov = template_overlaps()
    print(f"template overlaps flagged: {len(ov)}")
    for o in ov:
        print("  ", o)
    for name in ("cases_dev15.json", "cases_dev16.json"):
        cases, fam, st, distinct, severe = coverage(HERE.parent / name)
        print(f"\n{name}: {len(cases)} questions; families {dict(fam)}\n  sub-claims by status {dict(st)}\n  DISTINCT atoms by status {distinct}; severe-capable sub-claims {severe}")
        mixed = fam["mixed"]
        print(f"  mixed questions {mixed}: 80% retention needs {int(0.8 * mixed + 0.999)}; 95% lower bound at 80% observed: {wilson(int(0.8 * mixed), mixed)[0]:.0%}")
        for label, n in (("conflict (criterion 7)", distinct.get("CONFLICTED", 0)), ("negative-unsupported (criterion 8)", distinct.get("NEGATIVE_UNSUPPORTED", 0)), ("order (criterion 9)", distinct.get("ORDER_UNSUPPORTED", 0))):
            print(f"  {label}: {n} distinct atoms; zero events would only bound the rate below {upper_bound_zero(n):.0%} (95%)")
