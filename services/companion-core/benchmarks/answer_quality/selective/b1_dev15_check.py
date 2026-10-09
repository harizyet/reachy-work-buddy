"""Offline, no-model development check of the Stage B-1 deterministic pipeline against the dev15 gold atoms (development data: dev16 is NOT used and not touched).

Circularity disclosure: the relation cue and subject patterns come from the atoms' own `cue_re` / `subject_re`, written by the same author as the gold labels, so this measures the state logic and the sentence
reading, not generalisation to unseen relations. The discovery pool is the WHOLE invented corpus (every record), a harder pool than B1a retrieval. Authorisation follows the owner_private profile (sensitive records are not authorised). Not an acceptance result."""
from __future__ import annotations

import collections
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
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
KINDS = {"person": "person", "number": "number", "day": "day", "month": "month", "model": "model", "host": "host", "hours": "hours", "bool": "existence", "text": "person", "time": "time"}


def pool():
    c = json.loads((HERE / "corpus_v4.json").read_text())
    items = []
    created = NOW - timedelta(days=100)

    def add(ref, text, author, title=""):
        store, rid = ref.split(":", 1)
        items.append(DiscoveryItem(ref, text, {"store": store, "record_id": rid, "author_class": author, "created_at": created, "retrieved_at": NOW - timedelta(minutes=1), "acl_revision": 1}, title))

    for m in c["memories"]:
        add(f"memory:{m['id']}", m["text"], "owner")
    for n in c["notes"]:
        add(f"note:{n['id']}", n["body"], "owner", n.get("title", ""))
    for d in c["documents"]:
        add(f"document:{d['id']}", d["content"].replace("\n#", "\n"), "third_party", d.get("title", ""))
    for mt in c["meetings"]:
        for k, seg in enumerate(mt["segments"]):
            add(f"meeting:{mt['id']}", seg["text"], "attendee", mt.get("title", ""))
    # distinct ids per meeting segment would break provenance checks; keep one item per segment with a unique record id
    seen = {}
    fixed = []
    for it in items:
        n = seen.get(it.ref, 0)
        seen[it.ref] = n + 1
        if it.ref.startswith("meeting:"):
            ref = f"{it.ref}#{n}"
            fixed.append(DiscoveryItem(ref, it.text, it.provenance, it.title))
        else:
            fixed.append(it)
    return fixed


def main():
    items = pool()
    c4 = json.loads((HERE / "corpus_v4.json").read_text())
    level = {}
    for key, store in (("memories", "memory"), ("notes", "note"), ("documents", "document"), ("meetings", "meeting")):
        for r in c4[key]:
            level[f"{store}:{r['id']}"] = r.get("sensitivity", "public")
    # access profile owner_private: ceiling work-private, so `sensitive` records are NOT authorised (the access rule, applied here by the harness)
    auths = {i.ref: AuthDecision(level.get(i.ref.split("#")[0], "public") != "sensitive", NOW - timedelta(seconds=3), "p1", 1) for i in items}
    eids = {i.ref: f"E{n}" for n, i in enumerate(items, 1)}
    cases = json.loads((HERE.parent / "cases_dev15.json").read_text())["cases"]
    from validate_scorer import PEOPLE

    people = {p.lower() for p in PEOPLE} | {p.split()[0].lower() for p in PEOPLE}
    known = sorted({re.sub(r"\\b", "", a["subject_re"]) for q in cases for a in q["atoms"] if a["subject_re"]} - people - {p.replace(" ", "\\ ") for p in people})
    known = [k for k in known if k.replace("\\", "") not in people]
    conf = collections.Counter()
    by_rel = collections.Counter()
    bad = []
    for q in cases:
        for a in q["atoms"]:
            subject = re.sub(r"\\b", "", a["subject_re"])
            kind = KINDS.get(a["kind"], "person")
            spec = RelationSpec(a["relation"], kind, (a["cue_re"],), many=a["relation"] == "attends", co_subjects_ok=a["relation"] in ("runs_on", "default_model"), negation=r"\b(?:has no|does not have|there is no|no)\b", presence=r"\b(?:has a|has an|there is a)\b")
            ask = Ask.EXISTENCE if a["status"].startswith("NEGATIVE") else Ask.ORDERING if a["status"] == "ORDER_UNSUPPORTED" else Ask.VALUE
            scope = Scope.PAST if a["status"] == "HISTORICAL" else Scope.ANY
            comp = Component("c1", a["subject"], (subject,), a["relation"], ask, scope)
            plan = build_plan([comp], items, auths, now=NOW, specs={a["relation"]: spec}, eids=eids, known_subjects=[k for k in known if k != subject], policy=POLICY)
            got = plan.claims[0].state.value
            conf[(a["status"], got)] += 1
            by_rel[(a["relation"], a["status"], got)] += 1
            if got != a["status"]:
                bad.append((q["id"], a["status"], got, q["question"][:70], plan.tickets[0].reasons))
    total = sum(conf.values())
    ok = sum(v for (g, s), v in conf.items() if g == s)
    print(f"atoms {total}; state equals gold {ok} ({ok / total:.1%})")
    for (g, s), v in sorted(conf.items()):
        print(f"  gold {g:22s} -> {s:22s} {v}")
    print("disagreements by relation (relation, gold, got):")
    for (rel, g, s), v in sorted(by_rel.items()):
        if g != s:
            print(f"  {rel:22s} {g:12s} -> {s:12s} {v}")
    print("first disagreements:")
    for b in bad[:25]:
        print("  ", b)


if __name__ == "__main__":
    main()
