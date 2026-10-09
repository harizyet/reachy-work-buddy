"""Sampling plan of the scorer-v3 formal validation. Built from the corpus v5 worlds and the frozen seed ONLY: no reply and no scorer output exists or is consulted. One reply per (underlying fact, population);
arm and configuration are a seeded draw; sequences are seeded random orders, so labelling can stop at the event target using rater labels alone.

    python acceptance_plan.py [--worlds 31,32,...]  ->  acceptance/plan.json"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import acceptance_config as cfg
import fresh_v5_manifest as fm


def ukey(world: int, a: dict) -> str:
    rel = a.get("base_relation") if a["relation"] == "order_figure" else a["relation"]
    return f"{world}|{a['subject']}|{rel}"


def candidates(world: int):
    """(category -> {fact key -> (case id, atom index, atom id, status)}) for one world, preferring single-atom questions."""
    _, _, cases = fm.world(world)
    best: dict[tuple[str, str], tuple] = {}
    for c in cases:
        for i, a in enumerate(c["atoms"]):
            cats = []
            if a["status"] == "CONFLICTED":
                cats += ["conflict_resolution", "invented_ordering"]
            elif a["status"] == "ORDER_UNSUPPORTED":
                cats.append("invented_ordering")
            elif a["status"] == "NEGATIVE_UNSUPPORTED":
                cats.append("absence_or_presence_claim")
            elif a["status"] == "UNSUPPORTED" and a["kind"] in cfg.KIND_SEVERE:
                cats.append("leaked_value")
            elif a["status"] in cfg.CONTROL_STATUSES:
                cats.append("control")
            for cat in cats:
                # an ordering opportunity prefers the which-is-more-recent question over the conflict question for the same fact
                rank = (0 if (cat == "invented_ordering" and a["status"] == "ORDER_UNSUPPORTED") else 1, len(c["atoms"]), c["id"])
                key = (cat, ukey(world, a))
                if key not in best or rank < best[key][0]:
                    best[key] = (rank, c["id"], i, a["id"], a["status"])
    return {k: v[1:] for k, v in best.items()}


def build(worlds: list[int]) -> dict:
    per_cat: dict[str, list] = {c: [] for c in [*cfg.CATEGORIES, "control"]}
    for w in worlds:
        for (cat, fact), (case_id, idx, atom_id, status) in candidates(w).items():
            per_cat[cat].append({"fact": fact, "world": w, "case": case_id, "atom": idx, "atom_id": atom_id, "status": status})
    rnd = random.Random(cfg.SAMPLE_SEED)
    plan = {"seed": cfg.SAMPLE_SEED, "worlds": worlds, "sequences": {}}
    for pop in cfg.POPULATIONS:
        for cat in [*cfg.CATEGORIES, "control"]:
            items = sorted(per_cat[cat], key=lambda x: x["fact"] + x["case"])
            rnd.shuffle(items)
            if cat == "control":
                items = items[: cfg.CONTROLS_PER_POPULATION]
            seq = []
            for n, it in enumerate(items):
                arm = rnd.choice(cfg.ARMS)
                config = rnd.choice(cfg.CONFIGS[pop])[0]
                seq.append({**it, "key": f"{pop[0].upper()}-{cat[:3].upper()}-{n + 1:04d}", "arm": arm, "config": config})
            plan["sequences"][f"{pop}|{cat}"] = seq
    plan["counts"] = {k: len(v) for k, v in plan["sequences"].items()}
    return plan


if __name__ == "__main__":
    worlds = cfg.WORLDS
    if "--worlds" in sys.argv:
        worlds = [int(x) for x in sys.argv[sys.argv.index("--worlds") + 1].split(",")]
    plan = build(worlds)
    out = HERE / "acceptance" / ("plan.json" if worlds == cfg.WORLDS else "plan_expansion_" + "_".join(map(str, worlds[:1])) + ".json")
    out.write_text(json.dumps(plan, indent=1))
    print(plan["counts"], hashlib.sha256(out.read_bytes()).hexdigest())
