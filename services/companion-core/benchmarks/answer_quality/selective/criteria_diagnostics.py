"""Explain the two dev15 dry-run figures that sit on a threshold: criterion 4 (mixed questions fully correct: 26 of 30) and criterion 6 (cited claims whose cited ids do not all support them). Lists every
failing mixed question and every unsupported cited claim with the record each cites and the sources the case registers, so each is classified as a real defect or as support from a record the case does not
register (which only a person can judge). dev15 only; no model; the output is data, not a verdict.

    python criteria_diagnostics.py   -> results/i2b-dev15-criteria-diagnostics.md
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import deterministic_criteria as dc
import evaluator
import i2b_eval as e


def main() -> None:
    cases_list = json.loads((HERE.parent / "cases_dev15.json").read_text())["cases"]
    cases = {c["id"]: c for c in cases_list}
    w = e.World()
    rows = dc.candidate_rows(w, cases_list, e.make_planners(w, cases_list)["T-new"])
    out = ["# dev15 criteria diagnostics for the final candidate (T-new). Design set; an explanation, not a verdict.\n", "## Criterion 4: mixed questions that are not fully correct\n"]
    mixed = [r for r in rows if r["family"] == "mixed"]
    bad = [r for r in mixed if not evaluator.fully_correct_v3(r, cases[r["id"]])]
    out.append(f"{len(mixed) - len(bad)} of {len(mixed)} fully correct.\n")
    for r in bad:
        c = cases[r["id"]]
        why = []
        for a, ca in zip(r["outcome"]["atoms"], c["atoms"], strict=True):
            sup = evaluator.claim_supported(a, ca, r["manifest"])
            if not a["ok"] or a["wrong_value"] or sup is False:
                why.append(f"{ca['relation']}/{ca['pretty']} gold {a['status']}: " + ("not ok" if not a["ok"] else "") + (" unsupported citation" if sup is False else "") + (" false abstention" if a["false_abstention"] else ""))
        out += [f"- {r['id']}: {r['question']}  \n  reply: {r['reply']!r}  \n  why: {'; '.join(why) or 'a stray or untyped component'}"]
    out.append("\n## Criterion 6: cited claims whose cited ids do not all support the claim\n")
    n = k = 0
    lines = []
    for r in rows:
        c = cases[r["id"]]
        for a, ca in zip(r["outcome"]["atoms"], c["atoms"], strict=True):
            sup = evaluator.claim_supported(a, ca, r["manifest"])
            if sup is None:
                continue
            n += 1
            k += bool(sup)
            if not sup:
                recs = {i: w.ref_of.get(i) for i in a["cited_ids"]}
                lines.append(f"- {r['id']} {ca['relation']}/{ca['pretty']} ({a['status']}): cites {recs}; the case registers {ca['sources']}  \n  reply: {r['reply']!r}")
    out.append(f"{k} of {n} cited claims supported ({k / n:.1%}); {n - k} not.\n")
    out += lines
    (HERE.parent / "results" / "i2b-dev15-criteria-diagnostics.md").write_text("\n".join(out) + "\n")
    print(f"criterion 4: {len(mixed) - len(bad)}/{len(mixed)}; criterion 6: {k}/{n}")
    sys.stdout.write("\n".join(re.sub(r"\s+", " ", x)[:330] for x in lines) + "\n")


if __name__ == "__main__":
    main()
