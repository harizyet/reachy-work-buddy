"""A case-by-case review of a recorded report: for every case the question, the expected sources, the exclusions, why, what each
system returned and how it scored. It reads a report that already exists plus the fixtures; it never runs a retrieval system, so
producing it does not touch the holdout or its log."""

from __future__ import annotations

import json
from typing import Any

from kbench.fixtures import (
    ROOT,
    FixtureError,
    fixture_hashes,
    load_cases,
    load_corpus,
    source_meta,
    source_texts,
)
from kbench.scoring import dedupe, matches, same_source

SHOWN = 5


def rationale() -> dict[str, str]:
    return json.loads((ROOT / "review_rationale.json").read_text())["rationale"]


def _snippet(text: str, width: int = 90) -> str:
    flat = " ".join(text.split())
    return (flat[: width - 1] + "…") if len(flat) > width else flat


def _outcome(case: dict[str, Any], row: dict[str, Any]) -> str:
    m = row["metrics"]
    if case["category"] == "negative":
        return "false positive (returned something)" if m["returned_any"] else "clean (returned nothing)"
    if case["expected_refs"]:
        found, total = m["found@5"], m["expected_count"]
        verdict = "FULL" if found == total else ("PARTIAL" if found else "MISS")
        extra = []
        if m["temporal_ok"] is not None:
            extra.append("current fact " + ("ranked first" if m["temporal_ok"] else "NOT ahead of a stale one"))
        if row["leaks"]:
            extra.append(f"{len(row['leaks'])} unauthorized")
        return f"{verdict} {found}/{total} in top 5" + (f"; {'; '.join(extra)}" if extra else "")
    return f"{len(row['leaks'])} unauthorized hit(s) returned" if row["leaks"] else "clean (nothing unauthorized returned)"


def _list_hits(case: dict[str, Any], row: dict[str, Any]) -> str:
    expected, stale = case["expected_refs"], case.get("stale_refs", [])
    leaked = {leak["key"] for leak in row["leaks"]}
    keys = dedupe([h["key"] for h in row["hits"]])
    if not keys:
        return "nothing returned"
    marks = []
    for key in keys[:SHOWN]:
        flags = []
        flags.append("✓" if any(matches(key, e) for e in expected) else ("same source, other part" if any(same_source(key, e) for e in expected) else "✗"))
        if any(matches(key, s) for s in stale):
            flags.append("stale")
        if key in leaked:
            flags.append("UNAUTHORIZED: " + "/".join(sorted({leak["reason"] for leak in row["leaks"] if leak["key"] == key})))
        marks.append(f"`{key}` {' '.join(flags)}")
    out = "<br>".join(f"{i}. {m}" for i, m in enumerate(marks, 1))
    if len(keys) > SHOWN:
        out += f"<br>… {len(keys) - SHOWN} more returned"
    unauthorized_total = len({leak['key'] for leak in row["leaks"]})
    if unauthorized_total and unauthorized_total > sum(1 for k in keys[:SHOWN] if k in leaked):
        out += f" ({unauthorized_total} unauthorized in all)"
    missing = [e for e in expected if not any(matches(k, e) for k in keys)]
    if missing:
        out += "<br>not returned at all: " + ", ".join(f"`{e}`" for e in missing)
    return out


def _exclusions(case: dict[str, Any], profile: dict[str, Any], meta: dict[str, dict[str, Any]]) -> str:
    parts_out = []
    for forbidden in case.get("forbidden_refs", []):
        parts_out.append(f"`{forbidden['ref']}` ({forbidden['reason']})")
    for ref in case.get("stale_refs", []):
        parts_out.append(f"`{ref}` (superseded; must not outrank the current fact)")
    from kbench.security import violations

    by_rule: dict[str, int] = {}
    for key in meta:
        for reason in violations(key, meta, profile):
            by_rule[reason] = by_rule.get(reason, 0) + 1
    rule = ", ".join(f"{n} {reason}" for reason, n in sorted(by_rule.items())) or "none"
    listed = "; ".join(parts_out) if parts_out else "none listed"
    return f"{listed}. Excluded for this caller by the profile alone: {rule} source(s)."


def render(reports: dict[str, dict[str, Any]], split: str = "holdout") -> str:
    """`reports` maps a system name to its recorded report for `split`."""
    current = fixture_hashes()
    for name, report in reports.items():
        if report["split"] != split or report["fixtures"]["combined"] != current["combined"]:
            raise FixtureError(f"{name}: the recorded report is not for these fixtures; regenerate it before reviewing")
    corpus, cases, why = load_corpus(), load_cases(split), rationale()
    texts, meta = source_texts(corpus), source_meta(corpus)
    names = list(reports)
    rows = {n: {r["id"]: r for r in reports[n]["cases"]} for n in names}
    out = [
        f"# Phase 44A {split} case-level review",
        "",
        (
            f"Generated from the recorded reports {', '.join(f'`{n}`' for n in names)} (decision point `44A-baseline`, "
            f"synthetic-deterministic track) and the frozen fixtures (combined hash `{current['combined'][:16]}…`). No retrieval "
            "system was run to produce it, and the holdout log was not touched. The rationale text is the author's explanation "
            "of each label; it is not part of the frozen fixtures. **Status: the labels are provisionally reviewed, pending "
            "independent inspection by the owner.** The corpus is synthetic, so these results say nothing about real-world retrieval "
            "quality."
        ),
        "",
        (
            "Reading a case: **Expected** are the references a correct system must retrieve (a reference with `#n` names the exact "
            "chunk or segment). **Exclusions** are what must not be returned to that caller. A hit is marked ✓ (expected), `same "
            "source, other part` (right source, wrong chunk or segment), ✗ (not needed), `stale`, or `UNAUTHORIZED` with the rule it "
            f"breaks. Only the first {SHOWN} hits are listed. Recall is at 5."
        ),
        "",
        "## Summary",
        "",
        "| Case | Category | " + " | ".join(names) + " |",
        "|---|---|" + "---|" * len(names),
    ]
    for case in cases:
        out.append(f"| {case['id']} | {case['category']} | " + " | ".join(_outcome(case, rows[n][case["id"]]) for n in names) + " |")
    out += ["", "## Cases", ""]
    for case in cases:
        profile = corpus["access_profiles"][case["access"]]
        scopes = "all scopes" if profile["scopes"] is None else "scope " + ", ".join(profile["scopes"])
        context = (
            f"profile `{case['access']}` (ceiling {profile['ceiling']}, {scopes}, "
            f"{'private' if profile['channel_private'] else 'shared'} channel, may reach {', '.join(profile['destinations'])})"
            f"; attached meeting: {case['attached_meeting'] or 'none'}; {case['temporal'].replace('_', ' ')}"
        )
        out += [f"### {case['id']} · {case['category']}", "", f"**Query:** {case['question']}", "", f"**Context:** {context}", ""]
        if case["expected_refs"]:
            out.append("**Expected:**")
            out += [f"- `{ref}`: “{_snippet(texts[ref])}”" for ref in case["expected_refs"]]
        else:
            out.append("**Expected:** nothing; no source should be returned for this caller")
        out += ["", f"**Exclusions:** {_exclusions(case, profile, meta)}", "", f"**Why:** {why[case['id']]}"]
        if case.get("note"):
            out.append(f"\n*Fixture note:* {case['note']}")
        out += ["", "| | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        out.append("| **Retrieved** | " + " | ".join(_list_hits(case, rows[n][case["id"]]) for n in names) + " |")
        out.append("| **Recall@5, P@5, RR** | " + " | ".join(_fmt(rows[n][case["id"]]["metrics"]) for n in names) + " |")
        out.append("| **Outcome** | " + " | ".join(_outcome(case, rows[n][case["id"]]) for n in names) + " |")
        out.append("")
    return "\n".join(out) + "\n"


def _fmt(m: dict[str, Any]) -> str:
    if not m["expected_count"]:
        return "n/a (nothing expected)"
    return f"{m['recall@5']:.2f}, {m['precision@5']:.2f}, {m['rr']:.2f}"
