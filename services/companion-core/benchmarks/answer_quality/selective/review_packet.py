"""Build the manual-review packet for the FROZEN sample (review_sample_frozen.json) from the replies the I-2 follow-up produced. Run after i2b_eval.py. The packet lists, per sampled question, the question, the
gold structure, the reply of the gold-spec arm (G-registry) and of the question-text arm (T-new), and the text of every record the reply cites, so a reader can judge each reply against its own evidence.

Review rubric (written before any reply was read; one reader, the author of the pipeline: NO INDEPENDENT HUMAN REVIEW):
  READABILITY   3 reads as one clear answer to the question | 2 understandable but stilted or hard to follow | 1 confusing
  SEMANTICS     C every stated fact and every withholding is right for the question asked, judged against the cited records | P right but a reader would find the answer incomplete or oddly scoped | W a statement is wrong,
                or the reply answers a different question than the one asked
  IMPLICATION   N the reply implies nothing beyond its cited evidence | M a minor implication a careful reader could over-read | X a material implication the evidence does not support
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIG = list(sys.argv)
sys.path.insert(0, str(HERE))
import i2b_eval as e

OUT = HERE.parent / "results"


def main():
    sample = json.loads((HERE / "review_sample_frozen.json").read_text())
    w = e.World()
    cases = {c["id"]: c for c in json.loads((HERE.parent / "cases_dev15.json").read_text())["cases"]}
    arms = {a: {json.loads(line)["id"]: json.loads(line) for line in (OUT / f"i2b-dev15-replies-{a}.jsonl").read_text().splitlines()} for a in ("G-registry", "T-new")}
    lines = []
    for n, s in enumerate(sample["dev15"], 1):
        q = cases[s["id"]]
        g, t = arms["G-registry"][s["id"]], arms["T-new"][s["id"]]
        lines.append(f"### R{n:02d}  {s['id']}  [{s['stratum']}]\nQ: {q['question']}\nGOLD: {[(a['relation'], a['subject'], a['status'], a['display']) for a in q['atoms']]}")
        lines.append(f"GOLD-SPEC REPLY : {g['answer']!r}")
        lines.append(f"TEXT-ONLY REPLY : {t['answer']!r}" + ("   (identical)" if t["answer"] == g["answer"] else "   (DIFFERENT)"))
        for who, rep in (("T", t),):
            for eid in sorted(set(re.findall(r"\[(E\d+)\]", rep["answer"]))):
                ref = w.ref_of.get(eid)
                lines.append(f"  {eid} = {ref}: {w.texts.get(ref, '')[:230]!r}")
        lines.append("")
    (OUT / "i2b-review-packet.txt").write_text("\n".join(lines))
    print(len(sample["dev15"]), "questions in the packet")


if __name__ == "__main__":
    main()


def sweep_packet():
    """The nine frozen corpus-v5 existence facts (scoped-search negatives and three other absence classes) rendered by the unchanged I-1 path; the registry is not involved because these relations are not dev15's."""
    from datetime import timedelta

    import i2_existence_sweep as sw
    from companion_core.knowledge.answerability_b1 import (
        Ask,
        AuthDecision,
        Component,
        Scope,
        build_plan,
    )

    sample = json.loads((HERE / "review_sample_frozen.json").read_text())["existence_sweep"]
    sp = sw.specs()
    lines = []
    for n, s in enumerate(sample, 1):
        corpus, registry = sw.g5.build(s["seed"])
        items, level = sw.pool(corpus)
        auths = {i.ref: AuthDecision(level[i.ref] != "sensitive", sw.NOW - timedelta(seconds=3), "p1", 1) for i in items}
        eids = {i.ref: f"E{k}" for k, i in enumerate(items, 1)}
        from validate_scorer import PEOPLE

        known = [p for p in sorted({f["subject"] for f in registry["facts"]}) if p not in PEOPLE]
        comp = Component("c1", s["subject"], (s["subject"],), s["relation"], Ask.EXISTENCE, Scope.ANY)
        plan = build_plan([comp], items, auths, now=sw.NOW, specs=sp, eids=eids, known_subjects=[k for k in known if k != s["subject"]], policy=sw.POLICY)
        texts = {i.ref: i.text for i in items}
        lines.append(f"### S{n:02d}  seed {s['seed']}  condition={s['condition']}  {s['relation']} / {s['subject']}\nREPLY: {plan.answer!r}")
        for eid in sorted(set(re.findall(r"\[(E\d+)\]", plan.answer))):
            ref = next(r for r, v in eids.items() if v == eid)
            lines.append(f"  {eid} = {ref}: {texts[ref][:260]!r}")
        if s["condition"] == "unauthorized_only":
            lines.append("  (the only record that mentions it is not authorised for this profile and is not shown)")
        lines.append("")
    (OUT / "i2b-review-packet-sweep.txt").write_text("\n".join(lines))
    print(len(sample), "sweep facts rendered")


if __name__ == "__main__" and "--sweep" in ORIG:
    sweep_packet()
