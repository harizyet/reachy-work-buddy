"""Write results/i2b-dev15-failures.md from the last i2b_eval run: every dev15 sub-claim of the question-text arm (T-new) that is not an exact match, with its reply and a cause code. No model, no gold edit.

Cause codes: `decision_not_in_effect` = the only record that states the value is a decision or a plan (a decision is not a deployment, so it is reported as a decision and the question is withheld);
`ambiguity` = an authorised record about this subject and relation holds something that cannot be read safely; `no_admitted_record` = no sentence names the subject with the relation's cue (or the record is
excluded as instruction-bearing); `not_typed` = the decomposer withheld the clause.

    python i2b_failures.py
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

RES = Path(__file__).resolve().parent.parent / "results"


def main() -> None:
    report = json.loads((RES / "i2b-dev15-report.json").read_text())
    rows = {json.loads(line)["id"]: json.loads(line) for line in (RES / "i2b-dev15-replies-T-new.jsonl").read_text().splitlines()}
    out = ["# Remaining dev15 false abstentions of the question-text path (T-new) after the final development pass\n"]
    causes = collections.Counter()
    items = []
    for qid, aid, relation, gold, got, reasons in report["problems"]["T-new"].get("false_abstention", []):
        reply = rows[qid]["answer"]
        if got == "NOT_TYPED":
            cause = "not_typed"
        elif any(re.search(rf"A record says [^.]*? (?:was decided on|is planned) for the [^,]*{re.escape(g[1])}", reply) for g in rows[qid]["gold"] if g[0].replace("_history", "") == relation.replace("_history", "") and g[2] == gold):
            cause = "decision_not_in_effect"
        elif "ambiguity_on_requested_proposition" in reasons:
            cause = "ambiguity"
        else:
            cause = "no_admitted_record"
        causes[cause] += 1
        items.append((qid, aid, relation, gold, cause, rows[qid]))
    out.append(f"{sum(causes.values())} sub-claims: " + ", ".join(f"`{k}` {v}" for k, v in causes.most_common()) + "\n")
    for qid, aid, relation, gold, cause, row in items:
        want = next((g[3] for g in row["gold"] if g[0] == relation or relation in (g[0], g[0].replace("_history", ""))), "")
        out.append(f"- {qid} {relation} (gold {gold} {want}): cause `{cause}`  \n  Q: {row['question']}  \n  reply: {row['answer']!r}")
    (RES / "i2b-dev15-failures.md").write_text("\n".join(out) + "\n")
    print(dict(causes))


if __name__ == "__main__":
    main()
