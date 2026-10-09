"""Run the hand-labelled cases through the scorer; report agreement per flag and list every disagreement (known limits are marked)."""
from __future__ import annotations

import collections
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import scorer
from aq import cases as _cases  # noqa: F401
from scorer_cases import CASES

PEOPLE = ["Amara Osei", "Bruno Keller", "Chiara Rossi", "Dmitri Volkov", "Elena Marsh", "Farid Haddad", "Greta Lindqvist", "Hiro Tanaka", "Ines Duarte", "Jonas Weiss", "Kavya Menon", "Liam Oconnor", "Mila Novak", "Nikhil Rao",
          "Olga Petrova", "Pablo Reyes", "Quinn Abbott", "Rania Said", "Sven Larsen", "Tara Brennan", "Umar Bello", "Vera Kovac", "Wen Zhao", "Yusuf Demir"]
from scorer_cases import MAN


def run():
    results = []
    for c in CASES:
        out = scorer.score_question(c["reply"], c["atoms"], MAN, PEOPLE)
        diffs = []
        for i, exp in enumerate(c["expect"]):
            o = out.atoms[i]
            for k, v in exp.items():
                got = getattr(o, k)
                if got != v and not (v is False and got is None):
                    diffs.append((i, k, v, got))
        if c.get("bad") and out.bad_citations != c["bad"]:
            diffs.append((-1, "bad_citations", c["bad"], out.bad_citations))
        if c.get("unauth") and out.unauthorized_citations != c["unauth"]:
            diffs.append((-1, "unauthorized_citations", c["unauth"], out.unauthorized_citations))
        results.append((c, diffs))
    return results


if __name__ == "__main__":
    res = run()
    flags = collections.Counter()
    flag_ok = collections.Counter()
    for c, diffs in res:
        for i, exp in enumerate(c["expect"]):
            for k in exp:
                flags[k] += 1
        bad = {(i, k) for i, k, _, _ in diffs}
        for i, exp in enumerate(c["expect"]):
            for k in exp:
                if (i, k) not in bad:
                    flag_ok[k] += 1
    total = sum(flags.values())
    print(f"cases {len(res)}; flag decisions {total}; agreement {sum(flag_ok.values())}/{total} = {sum(flag_ok.values()) / total:.1%}")
    print({k: f"{flag_ok[k]}/{flags[k]}" for k in flags})
    fails = [(c, d) for c, d in res if d]
    print(f"cases with a disagreement: {len(fails)} (known limits: {sum(bool(c.get('limit')) for c, _ in fails)})")
    for c, d in fails:
        print(f"  {'[known limit] ' if c.get('limit') else ''}{c['name']}: {d}")
