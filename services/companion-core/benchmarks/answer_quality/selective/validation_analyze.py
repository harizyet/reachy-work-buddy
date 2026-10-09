"""Scorer-v2 validation: sampling, blinded packet, and the separate reporting of severe-error detection (owner decisions 2026-10-13).

  sample            draw the screening sample from the stored 7B replies by population x gold status ONLY (the scorer is not consulted), write the sample and a BLINDED packet
  report LABELS...  compare rater labels with the scorer: per population (natural / provoked / synthetic probes, never one headline), per severe category, sensitivity and precision with exact
                    (Clopper-Pearson) one-sided 95% lower and two-sided 95% bounds, false positives listed; overall flag agreement is a separate table
  probes            the synthetic probe population (labels by construction), reported on its own

Gate (owner): severe sensitivity one-sided 95% lower bound >= 90%, severe precision one-sided 95% lower bound >= 80%, no severe category with zero detection, every category reported separately.
Limits stated in every report: rater A is the assistant that wrote the scorer; without a second blinded human reviewer the validation is NOT independent human review."""
from __future__ import annotations

import importlib
import json
import random
import sys
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
AQ = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(AQ))
from validate_scorer import PEOPLE

FLAGS = ["stated", "identified", "false_abstention", "leaked", "severe", "wrong_value", "absence_claim", "invented_order", "both", "one_sided", "resolved", "as_current"]
SEED = 20261014
VAL = HERE / "validation"
QUOTA = {"natural": {"CONFLICTED": 60, "ORDER_UNSUPPORTED": 40, "NEGATIVE_UNSUPPORTED": 30, "UNSUPPORTED": 70, "OTHER": 60},
         "provoked": {"CONFLICTED": 50, "ORDER_UNSUPPORTED": 40, "NEGATIVE_UNSUPPORTED": 25, "UNSUPPORTED": 40}}
CATEGORIES = ["conflict_resolution", "invented_ordering", "absence_or_presence_claim", "leaked_value"]


# -- exact binomial bounds ---------------------------------------------------------------------------------------------------------------

def _tail_ge(k: int, n: int, p: float) -> float:
    return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def lower_bound(k: int, n: int, alpha: float) -> float:
    """Clopper-Pearson lower bound for k successes in n at one-sided level alpha."""
    if n == 0 or k == 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _tail_ge(k, n, mid) > alpha:
            hi = mid
        else:
            lo = mid
    return lo


def upper_bound(k: int, n: int, alpha: float) -> float:
    if n == 0:
        return 1.0
    if k == n:
        return 1.0
    return 1 - lower_bound(n - k, n, alpha)


def interval(k: int, n: int) -> dict:
    return {"estimate": round(k / n, 4) if n else None, "one_sided_95_lower": round(lower_bound(k, n, 0.05), 4), "two_sided_95": [round(lower_bound(k, n, 0.025), 4), round(upper_bound(k, n, 0.025), 4)], "k": k, "n": n}


# -- data -----------------------------------------------------------------------------------------------------------------------------

def load():
    rows = [json.loads(x) for x in (VAL / "replies_val17.jsonl").read_text().splitlines() if x.strip()]
    cases = {c["id"]: c for c in json.loads((AQ / "cases_val17.json").read_text())["cases"]}
    return rows, cases


def stratum(status: str, population: str) -> str | None:
    if status in QUOTA[population]:
        return status
    return "OTHER" if "OTHER" in QUOTA[population] else None


def sample():
    rows, cases = load()
    pool: dict[tuple, list] = defaultdict(list)
    for r in rows:
        for i, a in enumerate(cases[r["id"]]["atoms"]):
            s = stratum(a["status"], r["population"])
            if s:
                pool[(r["population"], s)].append((r["id"], r["arm"], r["config"], i))
    rng = random.Random(SEED)
    chosen = []
    pool_counts = {}
    for (population, s), items in sorted(pool.items()):
        items = sorted(items)
        rng.shuffle(items)
        pool_counts[f"{population}|{s}"] = len(items)
        per_atom: Counter = Counter()
        take = []
        for it in items:  # at most 4 replies per (case, atom) per stratum, so one atom cannot dominate
            key = (it[0], it[3])
            if per_atom[key] >= 4:
                continue
            per_atom[key] += 1
            take.append(it)
            if len(take) >= QUOTA[population][s]:
                break
        chosen += [(population, s, *t) for t in take]
    rng.shuffle(chosen)
    items = [{"key": f"V{k + 1:03d}", "population": p, "stratum": s, "case": c, "arm": arm, "config": cfg, "atom": i} for k, (p, s, c, arm, cfg, i) in enumerate(chosen)]
    by = {(r["id"], r["arm"], r["config"]): r for r in rows}
    packet = []
    for it in items:
        r = by[(it["case"], it["arm"], it["config"])]
        a = cases[it["case"]]["atoms"][it["atom"]]
        packet.append({"key": it["key"], "question": r["question"], "reply": r["reply"],
                       "atom": {"gold_status": a["status"], "sub_claim": f"{a['relation']} of {a['pretty']}", "gold_values": a.get("display", []), "kind": a["kind"]}, "evidence_ids_available": sorted(r["manifest"])})
    import hashlib

    pool_hash = hashlib.sha256((VAL / "replies_val17.jsonl").read_bytes()).hexdigest()
    (VAL / "validation_sample.json").write_text(json.dumps({"seed": SEED, "replies_sha256": pool_hash, "pool_counts": pool_counts, "quota": QUOTA, "items": items}, indent=1))
    (VAL / "validation_packet_BLINDED.json").write_text(json.dumps({"rubric": ["adjudication_rubric_v2.md", "adjudication_rubric_v3_addendum.md"], "flags": FLAGS, "items": packet}, indent=1))
    lines = ["# Blinded validation packet (scorer output withheld). Rubric: adjudication_rubric_v2.md + adjudication_rubric_v3_addendum.md", ""]
    for p in packet:
        lines += [f"## {p['key']}", f"Q: {p['question']}", f"Gold: {p['atom']['gold_status']}; sub-claim: {p['atom']['sub_claim']}; gold value(s): {p['atom']['gold_values']}", "Reply:", "> " + p["reply"].replace("\n", "\n> "), ""]
    (VAL / "validation_packet_BLINDED.md").write_text("\n".join(lines))
    print(len(items), Counter((i["population"], i["stratum"]) for i in items), "pool", pool_counts)


# -- scoring and categories -----------------------------------------------------------------------------------------------------------

def flags_of(o) -> dict:
    return {f: bool(getattr(o, f)) for f in FLAGS}


def categories(flags: dict, status: str) -> set[str]:
    """Severe-error categories present in a flag set (rater truth or scorer output), by one definition."""
    out = set()
    if flags["resolved"] and status == "CONFLICTED":
        out.add("conflict_resolution")
    if flags["invented_order"]:
        out.add("invented_ordering")
    if flags["absence_claim"] or (status == "NEGATIVE_UNSUPPORTED" and flags["leaked"]):
        out.add("absence_or_presence_claim")
    if status == "UNSUPPORTED" and flags["leaked"] and flags["severe"]:
        out.add("leaked_value")
    return out


def score_items(module_name: str):
    scorer = importlib.import_module(module_name)
    rows, cases = load()
    by = {(r["id"], r["arm"], r["config"]): r for r in rows}
    sample_ = json.loads((VAL / "validation_sample.json").read_text())
    out = {}
    cache: dict = {}
    for it in sample_["items"]:
        key = (it["case"], it["arm"], it["config"])
        if key not in cache:
            r = by[key]
            cache[key] = scorer.score_question(r["reply"], cases[it["case"]]["atoms"], r["manifest"], PEOPLE)
        out[it["key"]] = (flags_of(cache[key].atoms[it["atom"]]), cases[it["case"]]["atoms"][it["atom"]]["status"])
    return sample_, out


def cell(tp, fp, fn, tn):
    return {"tp": tp, "fn": fn, "fp": fp, "tn": tn, "sensitivity": interval(tp, tp + fn), "precision": interval(tp, tp + fp), "false_positives": fp}


def report(label_files: list[str], module="scorer_v2"):
    sample_, scored = score_items(module)
    labels = json.loads(Path(label_files[0]).read_text())
    rater = labels["labels"]
    second = json.loads(Path(label_files[1]).read_text())["labels"] if len(label_files) > 1 else None
    items = {i["key"]: i for i in sample_["items"]}
    result = {"scorer_module": module, "rater_a": labels.get("rater"), "independent_human_review": bool(second), "limitation": None if second else "NO INDEPENDENT HUMAN REVIEW: rater A is the assistant that wrote the scorer; this validation must not be described as independent human review.", "populations": {}}
    detail = {}
    for population in ("natural", "provoked"):
        keys = [k for k, i in items.items() if i["population"] == population and k in rater and not rater[k].get("unclear")]
        cats = {c: [0, 0, 0, 0] for c in (*CATEGORIES, "any_severe")}
        misses, fps = [], []
        agree = tot = 0
        for k in keys:
            truth = {f: f in rater[k]["flags"] for f in FLAGS}
            sc, status = scored[k]
            t_c, s_c = categories(truth, status), categories(sc, status)
            for c in CATEGORIES:
                tp_, fp_, fn_, tn_ = c in t_c and c in s_c, c in s_c and c not in t_c, c in t_c and c not in s_c, c not in t_c and c not in s_c
                for idx, v in enumerate((tp_, fp_, fn_, tn_)):
                    cats[c][idx] += v
                if fn_:
                    misses.append((k, c))
                if fp_:
                    fps.append((k, c))
            a_t, a_s = bool(t_c), bool(s_c)
            for idx, v in enumerate((a_t and a_s, a_s and not a_t, a_t and not a_s, not a_t and not a_s)):
                cats["any_severe"][idx] += v
            applicable = {"stated": {"SUPPORTED", "HISTORICAL", "NEGATIVE_SUPPORTED"}, "false_abstention": {"SUPPORTED", "HISTORICAL"}, "wrong_value": {"SUPPORTED", "HISTORICAL"}, "both": {"CONFLICTED"}, "one_sided": {"CONFLICTED"}, "as_current": {"HISTORICAL"}}
            for f in FLAGS:
                if status in applicable.get(f, {status}):
                    tot += 1
                    agree += truth[f] == sc[f]
        result["populations"][population] = {"items_rated": len(keys), "overall_flag_agreement": {"agree": agree, "of": tot, "rate": round(agree / tot, 4) if tot else None},
                                             "severe": {c: cell(*cats[c]) for c in cats}, "misses": misses, "false_positive_items": fps}
        detail[population] = (cats, misses, fps)
    # the gate, per population, never one pooled headline
    for population, pop in result["populations"].items():
        verdict = {}
        for c in CATEGORIES:
            cc = pop["severe"][c]
            events = cc["tp"] + cc["fn"]
            verdict[c] = {"events": events, "detected": cc["tp"], "zero_detection": events > 0 and cc["tp"] == 0, "sensitivity_lb_ok": cc["sensitivity"]["one_sided_95_lower"] >= 0.90 if events else None,
                          "precision_lb_ok": cc["precision"]["one_sided_95_lower"] >= 0.80 if (cc["tp"] + cc["fp"]) else None}
        a = pop["severe"]["any_severe"]
        verdict["pooled_over_categories_of_this_population"] = {"sensitivity_lb_ok": a["sensitivity"]["one_sided_95_lower"] >= 0.90, "precision_lb_ok": a["precision"]["one_sided_95_lower"] >= 0.80}
        pop["gate"] = verdict
    if second:
        both = [k for k in rater if k in second and not rater[k].get("unclear") and not second[k].get("unclear")]
        agree_k = sum(((set(rater[k]["flags"]) & {"leaked", "invented_order", "absence_claim", "resolved"}) != set()) == ((set(second[k]["flags"]) & {"leaked", "invented_order", "absence_claim", "resolved"}) != set()) for k in both)
        result["rater_agreement_on_severe_flag"] = {"items": len(both), "agree": agree_k}
    print(json.dumps(result, indent=1))
    return result


def probes(module="scorer_v2"):
    scorer = importlib.import_module(module)
    data = json.loads((VAL / "synthetic_probes.json").read_text())["probes"]
    per = defaultdict(lambda: [0, 0, 0, 0])
    misses, fps = [], []
    for p in data:
        o = scorer.score_question(p["reply"], p["atoms"], p["manifest"], PEOPLE).atoms[p["atom_index"]]
        sc = flags_of(o)
        status = p["atoms"][p["atom_index"]]["status"]
        s_sev = bool(categories(sc, status))
        t_sev = p["severe"]
        idx = (0 if t_sev and s_sev else 1 if s_sev else 2 if t_sev else 3)
        per[p["mechanism"]][idx] += 1
        if idx == 2:
            misses.append((p["id"], p["mechanism"], p["position"], p["phrase"], p["reply"]))
        if idx == 1:
            fps.append((p["id"], p["mechanism"], p["position"], p["phrase"], p["reply"]))
    out = {"scorer_module": module, "population": "synthetic probes (labels by construction, same-author)", "by_mechanism": {}, "misses_by_position": Counter(m[2] for m in misses), "n_misses": len(misses), "n_false_positives": len(fps)}
    for m, (tp, fp, fn, tn) in sorted(per.items()):
        out["by_mechanism"][m] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "detection": interval(tp, tp + fn) if tp + fn else None, "false_positive_rate": interval(fp, fp + tn) if fp + tn else None}
    out["miss_examples"] = [m[1:] for m in misses[:40]]
    out["false_positive_examples"] = [f[1:] for f in fps[:40]]
    print(json.dumps(out, indent=1, default=dict))
    return out


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "sample":
        sample()
    elif cmd == "report":
        module = "scorer_v2"
        args = [a for a in sys.argv[2:] if not a.startswith("--module=")]
        for a in sys.argv[2:]:
            if a.startswith("--module="):
                module = a.split("=", 1)[1]
        report(args, module)
    elif cmd == "probes":
        probes(sys.argv[2] if len(sys.argv) > 2 else "scorer_v2")
