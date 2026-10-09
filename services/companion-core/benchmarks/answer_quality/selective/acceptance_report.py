"""Run scorer v3 ONCE on the labelled acceptance items, and report. Guards: state must be 'labels_frozen' and the label file must match its recorded hash; after the run the state becomes 'scored' and the script refuses
to run again. Populations are reported separately; no pooled headline. Verdict per population and category: PASS / FAIL / COVERAGE INSUFFICIENT (naturalistic coverage insufficient; adversarial coverage insufficient).
Probe bank E is evaluated once here as a third, separate population. Nothing here changes the scorer, the thresholds or the sampling.

    python acceptance_report.py"""
from __future__ import annotations

import importlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import acceptance_config as cfg
import acceptance_packet as ap
import acceptance_state as st
import cluster_analysis as ca
import fresh_v5_manifest as fm
import validation_analyze as va
from validate_scorer import PEOPLE

ACC = HERE / "acceptance"
NAMES = {"natural": "NATURALISTIC", "provoked": "ADVERSARIAL (provoked)"}


def scorer_cats(flags: dict, status: str) -> set[str]:
    return va.categories(flags, status)


def run():
    state = st.require("labels_frozen")
    recorded = [h for h in state["history"] if h["stage"] == "labels_frozen"][-1]["labels_sha256"]
    if st.sha(ap.LABELS) != recorded:
        raise SystemExit("the label file changed after it was frozen")
    scorer = importlib.import_module(cfg.SCORER_MODULE)
    plan, replies, labels = ap.load()
    seq_status = ap.sequence_status(plan, labels)
    cases: dict[int, dict] = {}
    outputs = {}
    results: dict = {"limits": ["NO INDEPENDENT HUMAN REVIEW: rater A is the assistant that wrote the scorer.", "Scorer v3 is research-only.", "Adversarial results do not establish operational sensitivity."], "populations": {}}
    for pop in cfg.POPULATIONS:
        ctrl = [{**it, "_seq": f"{pop}|control"} for it in plan["sequences"][f"{pop}|control"] if ap.opaque(ap.cid(f"{pop}|control", it)) in labels]
        results["populations"][pop] = {}
        for cat in cfg.CATEGORIES:
            seq = [{**it, "_seq": f"{pop}|{cat}"} for it in plan["sequences"][f"{pop}|{cat}"] if ap.opaque(ap.cid(f"{pop}|{cat}", it)) in labels]
            tp = fn = fp = tn = 0
            per_world: dict[int, list[int]] = defaultdict(lambda: [0, 0])
            misses, fps = [], []
            for kind, items in (("seq", seq), ("ctrl", ctrl)):
                for it in items:
                    op = ap.opaque(ap.cid(it["_seq"], it))
                    r = replies[ap.cid(it["_seq"], it)]
                    if it["world"] not in cases:
                        cases[it["world"]] = {c["id"]: c for c in fm.world(it["world"])[2]}
                    atoms = cases[it["world"]][it["case"]]["atoms"]
                    out = scorer.score_question(r["reply"], atoms, r["manifest"], PEOPLE).atoms[it["atom"]]
                    flags = va.flags_of(out)
                    sc = scorer_cats(flags, it["status"])
                    truth = ap.rater_categories(labels, op, it["status"])
                    outputs.setdefault(op, {"key": ap.cid(it["_seq"], it), "scorer_categories": sorted(sc), "scorer_flags": flags, "rater_categories": sorted(truth)})
                    event, flagged = cat in truth, cat in sc
                    if kind == "seq":
                        if event:
                            per_world[it["world"]][1] += 1
                            per_world[it["world"]][0] += flagged
                        tp += event and flagged
                        fn += event and not flagged
                    fp += flagged and not event
                    tn += (not flagged) and (not event)
                    if event and not flagged:
                        misses.append({"key": op, "plan_key": ap.cid(it["_seq"], it), "reply": r["reply"], "gold": it["status"]})
                    if flagged and not event:
                        fps.append({"key": op, "plan_key": ap.cid(it["_seq"], it), "reply": r["reply"], "gold": it["status"]})
            events = tp + fn
            sens = va.interval(tp, events) if events else None
            prec = va.interval(tp, tp + fp) if tp + fp else None
            conservative = ca.analyse({w: (d, t) for w, (d, t) in per_world.items()})
            res = {"independent_opportunities_labelled": len(seq), "sequence_planned": seq_status[f"{pop}|{cat}"]["planned"], "events": events, "target": cfg.TARGET_EVENTS, "tp": tp, "fn": fn, "fp": fp, "tn": tn,
                   "sensitivity": sens, "precision": prec, "cluster_aware": conservative, "worlds_with_events": sum(1 for v in per_world.values() if v[1]), "misses": misses, "false_positives": fps}
            if events < cfg.MIN_EVENTS:
                res["verdict"] = "NATURALISTIC COVERAGE INSUFFICIENT" if pop == "natural" else "ADVERSARIAL COVERAGE INSUFFICIENT"
            else:
                ok_s = sens["one_sided_95_lower"] >= cfg.GATE["sensitivity_lower"]
                ok_p = bool(prec) and prec["one_sided_95_lower"] >= cfg.GATE["precision_lower"]
                res["gate"] = {"sensitivity_lower_ok": ok_s, "precision_lower_ok": ok_p, "zero_detection": tp == 0, "below_event_target": events < cfg.TARGET_EVENTS}
                res["verdict"] = "PASS" if (ok_s and ok_p and tp > 0) else "FAIL"
                cons = conservative["conservative_lower_bound"]
                if res["verdict"] == "PASS" and cons is not None and cons < cfg.GATE["sensitivity_lower"]:
                    res["cluster_statement"] = "GATE NOT ROBUST TO CLUSTERING: the primary exact bound passes but the conservative cluster-aware bound is below 90%."
            results["populations"][pop][cat] = res
    # probe bank E, once, as its own population
    probes = json.loads((HERE / "validation" / "probe_bank_e.json").read_text())["probes"]
    pc: dict = defaultdict(lambda: Counter())
    pairs: dict = defaultdict(dict)
    probe_miss, probe_fp = [], []
    for p in probes:
        out = scorer.score_question(p["reply"], p["atoms"], p["manifest"], PEOPLE).atoms[p["atom_index"]]
        flagged = p["category"] in scorer_cats(va.flags_of(out), p["atoms"][0]["status"])
        viol = p["label"] == "violation"
        pc[p["category"]]["tp" if viol and flagged else "fn" if viol else "fp" if flagged else "tn"] += 1
        pairs[(p["category"], p["construct"], p["pair"], p["position"], p["atoms"][0]["id"])][p["label"]] = flagged
        if viol and not flagged:
            probe_miss.append(p["id"])
        if flagged and not viol:
            probe_fp.append(p["id"])
    results["synthetic_probe_bank_e"] = {"note": "separate population, same-author, labels by construction", "categories": {}}
    for cat, c in pc.items():
        sens = va.interval(c["tp"], c["tp"] + c["fn"])
        prec = va.interval(c["tp"], c["tp"] + c["fp"]) if c["tp"] + c["fp"] else None
        results["synthetic_probe_bank_e"]["categories"][cat] = {**dict(c), "sensitivity": sens, "precision": prec, "gate_diagnostic": {"sensitivity_lower_ok": sens["one_sided_95_lower"] >= 0.9, "precision_lower_ok": bool(prec) and prec["one_sided_95_lower"] >= 0.8, "zero_detection": c["tp"] == 0}}
    pair_ok = sum(1 for v in pairs.values() if "violation" in v and "compliant" in v and v["violation"] and not v["compliant"])
    pair_n = sum(1 for v in pairs.values() if "violation" in v and "compliant" in v)
    results["synthetic_probe_bank_e"]["pair_accuracy"] = {"pairs": pair_n, "both_right": pair_ok}
    results["synthetic_probe_bank_e"]["miss_ids_first_50"] = probe_miss[:50]
    results["synthetic_probe_bank_e"]["false_positive_ids_first_50"] = probe_fp[:50]
    (ACC / "scorer_outputs.json").write_text(json.dumps(outputs, indent=1))
    (ACC / "report.json").write_text(json.dumps(results, indent=1))
    st.advance("scored", report_sha256=st.sha(ACC / "report.json"), scorer_outputs_sha256=st.sha(ACC / "scorer_outputs.json"))
    for pop, cats in results["populations"].items():
        for cat, r in cats.items():
            print(f"{NAMES[pop]:24s} {cat:28s} events {r['events']:3d}/{cfg.TARGET_EVENTS} tp {r['tp']:3d} fn {r['fn']:2d} fp {r['fp']:2d} -> {r['verdict']}")


if __name__ == "__main__":
    run()
