"""Build the review packets for the final development pass (2026-10-10). Run after i2b_eval.py. Three outputs, all single-reader material (NO INDEPENDENT HUMAN REVIEW):

  results/i2b-review-packet-b.txt          the 28 PROSPECTIVE dev15 questions (frozen in review_sample_b_frozen.json, never part of the earlier 51) with the reply before and after this pass, and the
                                           records each reply cites; plus the 14 fresh synthetic probes (transition_probes.py) with their expected states checked.
  results/i2b-review-regression-51.txt     the 51 PREVIOUSLY INSPECTED items (review_sample_frozen.json), before and after. This is a regression check on development material the author has read before; it is not
                                           a fresh review and says nothing about unseen text.
  results/i2b-review-b-probe-check.json    the probe state check (exact, not wording).

Rubric (unchanged from the earlier review, written before any reply was read): READABILITY 3 clear | 2 stilted | 1 confusing; SEMANTICS C correct | P right but incomplete | W wrong; IMPLICATION N none | M minor |
X material.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIG = list(sys.argv)
sys.path.insert(0, str(HERE))
import i2b_eval as e
from companion_core.knowledge.answerability_b1 import (
    AdmissionPolicy,
    AuthDecision,
    DiscoveryItem,
)
from companion_core.knowledge.answerability_b1.questions import plan_question
from companion_core.knowledge.answerability_b1.registry import Registry

OUT = HERE.parent / "results"
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def verify() -> None:
    for name in ("REVIEW_SAMPLE_B_FREEZE.sha256", "TRANSITION_PROBES.sha256", "REVIEW_SAMPLE_FREEZE.sha256"):
        for line in (HERE / name).read_text().splitlines():
            if line.startswith("#") or not line.strip():
                continue
            digest, fname = line.split()
            if hashlib.sha256((HERE / fname).read_bytes()).hexdigest() != digest:
                raise SystemExit(f"FROZEN FILE CHANGED: {fname}")


def load(path: Path) -> dict:
    return {json.loads(line)["id"]: json.loads(line) for line in path.read_text().splitlines()}


def cited_text(w: e.World, reply: str) -> list[str]:
    out = []
    for eid in sorted(set(re.findall(r"\[(E\d+)\]", reply))):
        ref = w.ref_of.get(eid)
        out.append(f"    {eid} = {ref}: {w.texts.get(ref, '')[:230]!r}")
    return out


def main() -> None:
    verify()
    w = e.World()
    cases = {c["id"]: c for c in json.loads((HERE.parent / "cases_dev15.json").read_text())["cases"]}
    after, before = load(OUT / "i2b-dev15-replies-T-new.jsonl"), load(OUT / "i2b-dev15-replies-T-new.before-final-pass.jsonl")
    sample = json.loads((HERE / "review_sample_b_frozen.json").read_text())

    lines = ["PROSPECTIVE DEVELOPMENT REVIEW PACKET (changed wording). Single reader: NO INDEPENDENT HUMAN REVIEW. dev15 = design set.\n"]
    for n, s in enumerate(sample["dev15"], 1):
        q = cases[s["id"]]
        lines += [f"### B{n:02d}  {s['id']}  [{s['stratum']}]", f"Q: {q['question']}", f"GOLD: {[(a['relation'], a['subject'], a['status'], a['display']) for a in q['atoms']]}",
                  f"BEFORE: {before[s['id']]['answer']!r}", f"AFTER : {after[s['id']]['answer']!r}" + ("   (identical)" if after[s['id']]['answer'] == before[s['id']]['answer'] else "   (CHANGED)"), *cited_text(w, after[s["id"]]["answer"]), ""]

    reg = Registry()
    checks, lines_p = [], ["\nFRESH SYNTHETIC PROBES (transition_probes.py)\n"]
    import transition_probes as tp
    for pr in tp.PROBES:
        items, auths, eids = [], {}, {}
        for n, (ref, author, text) in enumerate(pr["records"], 1):
            store, rid = ref.split(":", 1)
            items.append(DiscoveryItem(ref, text, {"store": store, "record_id": rid, "author_class": author, "created_at": NOW - timedelta(days=30), "retrieved_at": NOW - timedelta(minutes=1), "acl_revision": 1}, "Marten planning" if store == "meeting" else ""))
            auths[ref] = AuthDecision(True, NOW - timedelta(seconds=5), "p1", 1)
            eids[ref] = f"E{n}"
        plan, _dec = plan_question(pr["q"], reg, items, auths, now=NOW, eids=eids, policy=AdmissionPolicy(expected_policy_version="p1"))
        got = ["SUBJECT_TYPE_WITHHELD" if "clause_not_understood" in c.reasons else c.state.value for c in plan.claims]
        ok = got == pr["expect"]
        checks.append({"id": pr["id"], "expected": pr["expect"], "got": got, "ok": ok})
        lines_p += [f"### {pr['id']}  state check {'OK' if ok else 'MISMATCH'}: expected {pr['expect']} got {got}", f"Q: {pr['q']}", *[f"  record {r}: {t!r} ({a})" for r, a, t in pr["records"]], f"REPLY: {plan.answer!r}", ""]
    (OUT / "i2b-review-packet-b.txt").write_text("\n".join(lines + lines_p))
    (OUT / "i2b-review-b-probe-check.json").write_text(json.dumps({"probes": len(checks), "state_matches": sum(c["ok"] for c in checks), "checks": checks}, indent=1))

    prior = json.loads((HERE / "review_sample_frozen.json").read_text())
    reg_lines = ["REGRESSION CHECK on the 51 PREVIOUSLY INSPECTED items (development material the author has already read). Before = the previous iteration's reply, after = this pass.\n"]
    changed = 0
    for n, s in enumerate(prior["dev15"], 1):
        same = after[s["id"]]["answer"] == before[s["id"]]["answer"]
        changed += not same
        reg_lines += [f"### R{n:02d}  {s['id']}  [{s['stratum']}]  {'(identical)' if same else '(CHANGED)'}", f"Q: {cases[s['id']]['question']}"]
        if not same:
            reg_lines += [f"BEFORE: {before[s['id']]['answer']!r}", f"AFTER : {after[s['id']]['answer']!r}"]
        reg_lines.append("")
    (OUT / "i2b-review-regression-51.txt").write_text("\n".join(reg_lines))
    print(f"prospective {len(sample['dev15'])} dev15 + {len(checks)} probes (state matches {sum(c['ok'] for c in checks)}); regression 51: {changed} changed, {51 - changed} identical")


if __name__ == "__main__":
    main()
