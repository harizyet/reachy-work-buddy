"""I-2 supplement: the four existence families x six evidence conditions of corpus v5, on FRESH DEVELOPMENT worlds (seeds 101 and 102; in no manifest, none of the 18 scorer-validation worlds 31-48 is used).
No model. Measures the three absence classes (rubric v5) end to end through the deterministic path: expected state per condition, wording, and the properties that must never fail (no world-level absence from a
scoped search, unauthorised-only evidence indistinguishable from silence, no value-less claim without a citation). Specs are written from the family wording (disclosed: same author as the corpus).

    python i2_existence_sweep.py   -> results/i2-existence-sweep.json
"""
from __future__ import annotations

import collections
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "src"))
import corpus_gen_v5 as g5
from companion_core.knowledge.answerability_b1 import (
    AdmissionPolicy,
    Ask,
    AuthDecision,
    Component,
    DiscoveryItem,
    RelationSpec,
    Scope,
    build_plan,
)

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
POLICY = AdmissionPolicy(expected_policy_version="p1")
SEEDS = (101, 102)
EXPECT = {"explicit_absence": "NEGATIVE_SUPPORTED", "incomplete_scope": "NEGATIVE_UNSUPPORTED", "source_disagreement": "CONFLICTED", "other_authorized_source": "SUPPORTED", "unauthorized_only": "NEGATIVE_UNSUPPORTED", "silent": "NEGATIVE_UNSUPPORTED"}
WORLD_LEVEL = re.compile(r"\b(?:there is no|has no|does not have)\b|\bno (?:run-?book|on-call rotation|escalation channel|status page)\b")


def specs():
    out = {}
    for rel, fam in g5.FAMILIES.items():
        out[rel] = RelationSpec(rel, "existence", (fam["cue"],), negation=r"\b(?:has no|does not have|there is no|no)\b", presence=r"\b(?:has an?|there is an?|this is the)\b", phrase=fam["noun"], joiner="for")
    return out


def pool(corpus):
    items, level = [], {}
    created = NOW - timedelta(days=60)

    def add(ref, text, author, sens, title=""):
        store, rid = ref.split(":", 1)
        items.append(DiscoveryItem(ref, text, {"store": store, "record_id": rid, "author_class": author, "created_at": created, "retrieved_at": NOW - timedelta(minutes=1), "acl_revision": 1}, title))
        level[ref] = sens

    for m in corpus["memories"]:
        add(f"memory:{m['id']}", m["text"], m.get("author_class", "owner"), m.get("sensitivity", "work-private"))
    for n in corpus["notes"]:
        add(f"note:{n['id']}", n["body"], n.get("author_class", "owner"), n.get("sensitivity", "work-private"), n.get("title", ""))
    for d in corpus["documents"]:
        add(f"document:{d['id']}", d["content"], d.get("author_class", "third_party"), d.get("sensitivity", "work-private"), d.get("title", ""))
    return items, level


def main():
    sp = specs()
    rows = collections.Counter()
    by_condition = collections.defaultdict(collections.Counter)
    problems, examples = [], {}
    for seed in SEEDS:
        corpus, registry = g5.build(seed)
        items, level = pool(corpus)
        auths = {i.ref: AuthDecision(level[i.ref] != "sensitive", NOW - timedelta(seconds=3), "p1", 1) for i in items}
        eids = {i.ref: f"E{n}" for n, i in enumerate(items, 1)}
        projects = sorted({f["subject"] for f in registry["facts"]})
        from validate_scorer import PEOPLE

        known = [p for p in projects if p not in PEOPLE]  # people are not competing subjects (the dev15 harness excludes them too)
        for f in registry["facts"]:
            if f["relation"] not in g5.FAMILIES:
                continue
            subject = f["subject"]
            comp = Component("c1", subject, (subject,), f["relation"], Ask.EXISTENCE, Scope.ANY)
            plan = build_plan([comp], items, auths, now=NOW, specs=sp, eids=eids, known_subjects=[k for k in known if k != subject], policy=POLICY)
            claim, ticket = plan.claims[0], plan.tickets[0]
            cond, want, got = f["state"], EXPECT[f["state"]], claim.state.value
            rows["facts"] += 1
            by_condition[cond][got] += 1
            ok = want == got
            rows["state_equals_expected"] += ok
            if not ok:
                problems.append((seed, subject, f["relation"], cond, want, got, claim.text[:160]))
            if WORLD_LEVEL.search(claim.text.replace("found no", "")) and got != "NEGATIVE_SUPPORTED":
                rows["WORLD_LEVEL_ABSENCE_WITHOUT_AUTHORITY"] += 1
                problems.append((seed, subject, f["relation"], cond, "world-level wording", got, claim.text))
            if cond == "incomplete_scope":
                rows["scoped_cases"] += 1
                rows["scoped_form_rendered"] += bool(ticket.scoped) and "A search of" in claim.text and "That does not show there is none." in claim.text
                rows["scoped_with_unsearched_part_quoted"] += bool(ticket.scoped) and "not searched:" in claim.text
                examples.setdefault("incomplete_scope", claim.text)
            if cond == "unauthorized_only":  # the unauthorised record must be indistinguishable from not existing: same reply, byte for byte, when it is removed from the pool entirely
                restricted = {r for r in level if level[r] == "sensitive"}
                p2 = build_plan([comp], [i for i in items if i.ref not in restricted], auths, now=NOW, specs=sp, eids=eids, known_subjects=[k for k in known if k != subject], policy=POLICY)
                rows["unauthorized_only_cases"] += 1
                rows["unauthorized_only_identical_to_record_absent"] += p2.claims[0].text == claim.text
            if got in ("SUPPORTED", "NEGATIVE_SUPPORTED") or (got == "NEGATIVE_UNSUPPORTED" and ticket.scoped):
                rows["asserted_or_reported_with_citation"] += 1
                rows["with_citation"] += bool(claim.assertable) and all(f"[{e}]" in claim.text for _, ids in claim.assertable for e in ids)
            examples.setdefault(cond, claim.text)
    report = {"seeds": list(SEEDS), "facts": rows["facts"], "counts": dict(rows), "confusion_by_condition": {k: dict(v) for k, v in by_condition.items()}, "examples": examples, "problems": problems}
    out = HERE.parent / "results" / "i2-existence-sweep.json"
    out.write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != "problems"}, indent=1, default=str))
    print("problems:", len(problems))
    for p in problems[:12]:
        print("  ", p)


if __name__ == "__main__":
    main()
