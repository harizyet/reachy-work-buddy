"""Fresh scorer adjudication (owner-approved 2026-10-12). Rubric: adjudication_rubric_v2.md (frozen by hash before the sample is drawn).

  sample   draw the sample from stored dev15 7B replies not used in the first adjudication, stratified by atom status/family only (scorer output is not used for selection); write the sample and a
           BLINDED packet (no scorer flags) for the raters
  report   compare rater label files with the scorer's current output; agreement overall, by category and for severe-error detection

No model is called and dev16 is not touched. Rows come from results/pilot-dev15-7b.json (the production 7B on the invented dev15 design questions)."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scorer
from evaluator import wilson
from validate_scorer import PEOPLE

AQ = HERE.parent
SEED = 20261013
QUOTA = {"CONFLICTED": 28, "ORDER_UNSUPPORTED": 10, "NEGATIVE_UNSUPPORTED": 7, "NEGATIVE_SUPPORTED": 9, "HISTORICAL": 30, "UNSUPPORTED": 28, "SUPPORTED": 30}
HARD_FAMILIES = {"multipart", "unknown_actor", "mixed"}
FLAGS = ["stated", "identified", "false_abstention", "leaked", "severe", "wrong_value", "absence_claim", "invented_order", "both", "one_sided", "resolved", "as_current"]
CATEGORY = lambda status, family: (
    status if status in {"CONFLICTED", "ORDER_UNSUPPORTED", "NEGATIVE_UNSUPPORTED", "NEGATIVE_SUPPORTED", "HISTORICAL"}
    else ("SUPPORTED_" + ("multipart_unknown_actor" if family in {"multipart", "unknown_actor"} else "other")) if status == "SUPPORTED"
    else ("UNSUPPORTED_" + ("mixed_multipart_unknown_actor" if family in HARD_FAMILIES else "other")))


def load():
    rows = json.loads((AQ / "results" / "pilot-dev15-7b.json").read_text())["rows"]
    cases = {c["id"]: c for c in json.loads((AQ / "cases_dev15.json").read_text())["cases"]}
    return rows, cases


def sample():
    rows, cases = load()
    used = {(a, b, c) for a, b, c in json.loads((HERE / "adjudication_sample.json").read_text())}
    pool: dict[str, list] = {}
    for r in rows:
        for i, a in enumerate(cases[r["id"]]["atoms"]):
            if (r["id"], r["arm"], i) not in used:
                pool.setdefault(a["status"], []).append((r["id"], r["arm"], i, r["family"]))
    rng = random.Random(SEED)
    chosen = []
    for status, n in QUOTA.items():
        p = sorted(pool[status])
        if status in ("SUPPORTED", "UNSUPPORTED"):
            hard = [x for x in p if x[3] in HARD_FAMILIES]
            rest = [x for x in p if x[3] not in HARD_FAMILIES]
            rng.shuffle(hard)
            rng.shuffle(rest)
            take = hard[: n // 2 + n % 2] + rest[: n // 2]
            take += [x for x in hard[n // 2 + n % 2:] + rest[n // 2:]][: n - len(take)]
        else:
            rng.shuffle(p)
            take = p[:n]
        chosen += take
    rng.shuffle(chosen)
    items = [{"key": f"F{k+1:03d}", "case": c, "arm": arm, "atom": i, "category": CATEGORY(cases[c]["atoms"][i]["status"], fam)} for k, (c, arm, i, fam) in enumerate(chosen)]
    (HERE / "adjudication_fresh_sample.json").write_text(json.dumps({"seed": SEED, "rubric_sha256": (HERE / "adjudication_rubric_v2.sha256").read_text().split()[0], "items": items}, indent=1))
    by = {(r["id"], r["arm"]): r for r in rows}
    packet = []
    for it in items:
        r = by[(it["case"], it["arm"])]
        a = cases[it["case"]]["atoms"][it["atom"]]
        packet.append({"key": it["key"], "question": r["question"], "reply": r["reply"],
                       "atom": {"gold_status": a["status"], "sub_claim": f"{a['relation']} of {a['pretty']}", "gold_values": a.get("display", []), "kind": a["kind"]},
                       "evidence_ids_available": sorted(r["manifest"])})
    (HERE / "adjudication_fresh_packet_BLINDED.json").write_text(json.dumps({"rubric": "adjudication_rubric_v2.md", "flags": FLAGS, "items": packet}, indent=1))
    lines = ["# Blinded adjudication packet (scorer flags withheld). Rubric: adjudication_rubric_v2.md", ""]
    for p in packet:
        lines += [f"## {p['key']}", f"Q: {p['question']}", f"Gold: {p['atom']['gold_status']}; sub-claim: {p['atom']['sub_claim']}; gold value(s): {p['atom']['gold_values']}", "Reply:", "> " + p["reply"].replace("\n", "\n> "), ""]
    (HERE / "adjudication_fresh_packet_BLINDED.md").write_text("\n".join(lines))
    from collections import Counter
    print(len(items), Counter(i["category"] for i in items))


def scorer_flags():
    rows, cases = load()
    by = {(r["id"], r["arm"]): r for r in rows}
    out = {}
    for it in json.loads((HERE / "adjudication_fresh_sample.json").read_text())["items"]:
        r = by[(it["case"], it["arm"])]
        case = cases[it["case"]]
        o = scorer.score_question(r["reply"], case["atoms"], r["manifest"], PEOPLE).atoms[it["atom"]]
        out[it["key"]] = {f: bool(getattr(o, f)) for f in FLAGS}
    return out


# Flag applicability fixed by the frozen rubric text (stated: SUPPORTED/HISTORICAL/NEGATIVE_SUPPORTED; false_abstention: SUPPORTED/HISTORICAL; wrong_value: SUPPORTED/HISTORICAL; both/one_sided/resolved: CONFLICTED;
# as_current: HISTORICAL). The scorer also sets stated/false_abstention on other statuses; those are reported as "raw" only.
APPLICABLE = {"stated": {"SUPPORTED", "HISTORICAL", "NEGATIVE_SUPPORTED"}, "false_abstention": {"SUPPORTED", "HISTORICAL"}, "wrong_value": {"SUPPORTED", "HISTORICAL"},
              "both": {"CONFLICTED"}, "one_sided": {"CONFLICTED"}, "as_current": {"HISTORICAL"}}


def severe(f):
    return f["leaked"] and f["severe"] or f["invented_order"] or f["absence_claim"] or f["resolved"]


def report(label_file: str):
    global STATUS
    STATUS = {(c["id"], i): a["status"] for c in json.loads((AQ / "cases_dev15.json").read_text())["cases"] for i, a in enumerate(c["atoms"])}
    items = {i["key"]: i for i in json.loads((HERE / "adjudication_fresh_sample.json").read_text())["items"]}
    labels = json.loads(Path(label_file).read_text())["labels"]
    sc = scorer_flags()
    tot = {}
    raw = [0, 0]
    cat: dict[str, list[int]] = {}
    disagreements = []
    sev = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    per_item_exact = 0
    n = 0
    for k, it in items.items():
        lab = labels.get(k)
        if lab is None or lab.get("unclear"):
            continue
        truth = {f: f in lab["flags"] for f in FLAGS}
        n += 1
        status = json.loads((AQ / "cases_dev15.json").read_text())["cases"] and STATUS[(it["case"], it["atom"])]
        raw_diff = [f for f in FLAGS if truth[f] != sc[k][f]]
        raw[0] += len(FLAGS) - len(raw_diff)
        raw[1] += len(FLAGS)
        diff = [f for f in raw_diff if status in APPLICABLE.get(f, {status})]
        per_item_exact += not diff
        c = cat.setdefault(it["category"], [0, 0, 0, 0])
        c[0] += 1
        c[1] += not diff
        c[2] += len(FLAGS) - len(diff)
        c[3] += len(FLAGS)
        tot_a, tot_b = tot.get("a", 0), tot.get("b", 0)
        tot["a"], tot["b"] = tot_a + len(FLAGS) - len(diff), tot_b + len(FLAGS)
        t, s = severe(truth), severe(sc[k])
        sev["tp" if t and s else "fn" if t else "fp" if s else "tn"] += 1
        if diff:
            disagreements.append({"key": k, "category": it["category"], "flags_rater_vs_scorer": {f: [truth[f], sc[k][f]] for f in diff}})
    res = {"items_rated": n, "raw_flag_agreement_all_flags_all_statuses": f"{raw[0]}/{raw[1]} = {raw[0]/raw[1]:.4f}", "flag_decisions": f"{tot['a']}/{tot['b']}", "flag_agreement": round(tot["a"] / tot["b"], 4), "flag_agreement_wilson95": [round(x, 4) for x in wilson(tot["a"], tot["b"])],
           "item_exact_match": f"{per_item_exact}/{n}", "by_category": {k: {"items": v[0], "exact": f"{v[1]}/{v[0]}", "flag_agreement": round(v[2] / v[3], 4)} for k, v in sorted(cat.items())},
           "severe_detection": {**sev, "sensitivity": round(sev["tp"] / max(1, sev["tp"] + sev["fn"]), 4), "specificity": round(sev["tn"] / max(1, sev["tn"] + sev["fp"]), 4),
                                "sensitivity_wilson95": [round(x, 4) for x in wilson(sev["tp"], sev["tp"] + sev["fn"])]}, "disagreements": disagreements}
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    {"sample": sample, "report": lambda: report(sys.argv[2])}[sys.argv[1]]()
