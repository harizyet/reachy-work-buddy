"""Blinded labelling workflow for the formal validation. The packet shows question, reply, gold status and values, evidence ids, under an opaque key; no scorer output exists at this stage and the
population is not shown. Sequence order is the seeded plan order, and a (population, category) sequence stops when its rater-confirmed event count reaches the target or it is exhausted: stopping uses labels only.

    python acceptance_packet.py next     -> acceptance/packet_blockNN.md (+ private key map)
    python acceptance_packet.py status   -> labelled / confirmed events / done per sequence"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import acceptance_config as cfg
import fresh_v5_manifest as fm
import validation_analyze as va

ACC = HERE / "acceptance"
LABELS = ACC / "labels_raterA.json"
FLAGS = va.FLAGS


def opaque(key: str) -> str:
    return "Q" + hashlib.sha256(f"{cfg.SAMPLE_SEED}|{key}".encode()).hexdigest()[:7]


def load():
    plan = json.loads((ACC / "plan.json").read_text())
    replies = {r["key"]: r for r in map(json.loads, (ACC / "replies.jsonl").read_text().splitlines())}
    labels = json.loads(LABELS.read_text())["labels"] if LABELS.exists() else {}
    return plan, replies, labels


def rater_categories(labels: dict, op: str, status: str) -> set[str]:
    lab = labels.get(op)
    if lab is None or lab.get("unclear"):
        return set()
    return va.categories({f: f in lab["flags"] for f in FLAGS}, status)


def sequence_status(plan, labels):
    out = {}
    for name, seq in plan["sequences"].items():
        _pop, cat = name.split("|")
        labelled = [it for it in seq if opaque(it["key"]) in labels]
        events = sum(1 for it in labelled if cat in rater_categories(labels, opaque(it["key"]), it["status"]))
        done = cat == "control" and len(labelled) >= len(seq) or (cat != "control" and (events >= cfg.TARGET_EVENTS or len(labelled) >= len(seq)))
        out[name] = {"planned": len(seq), "labelled": len(labelled), "confirmed_events": events, "done": done}
    return out


def build_next():
    plan, replies, labels = load()
    status = sequence_status(plan, labels)
    cases = {}
    items = []
    for name, seq in plan["sequences"].items():
        if status[name]["done"]:
            continue
        pending = [it for it in seq if opaque(it["key"]) not in labels and it["key"] in replies][: cfg.LABEL_BLOCK]
        items += [{**it, "sequence": name} for it in pending]
    if not items:
        print("nothing left to label")
        return
    items.sort(key=lambda it: opaque(it["key"]))  # opaque order: sequences are interleaved and not recognisable
    for it in items:
        w = it["world"]
        if w not in cases:
            cases[w] = {c["id"]: c for c in fm.world(w)[2]}
    n = len(list(ACC.glob("packet_block*.md"))) + 1
    lines = ["# Blinded acceptance packet (no scorer output exists). Rubric: v2 + v3 addendum + v4 addendum", ""]
    keymap = json.loads((ACC / "packet_map.json").read_text()) if (ACC / "packet_map.json").exists() else {}
    for it in items:
        r = replies[it["key"]]
        a = cases[it["world"]][it["case"]]["atoms"][it["atom"]]
        op = opaque(it["key"])
        keymap[op] = it["key"]
        lines += [f"## {op}", f"Q: {r['question']}", f"Gold: {a['status']}; sub-claim: {a['relation']} of {a['pretty']}; gold value(s): {a.get('display', [])}", "Reply:", "> " + r["reply"].replace("\n", "\n> "), ""]
    (ACC / f"packet_block{n:02d}.md").write_text("\n".join(lines))
    (ACC / "packet_map.json").write_text(json.dumps(keymap))
    print(f"block {n}: {len(items)} items")


if __name__ == "__main__":
    if sys.argv[1] == "next":
        build_next()
    else:
        plan, _, labels = load()
        for name, s in sequence_status(plan, labels).items():
            print(f"{name:42s} planned {s['planned']:4d} labelled {s['labelled']:4d} confirmed events {s['confirmed_events']:3d} done {s['done']}")
