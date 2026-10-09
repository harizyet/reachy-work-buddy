"""Replay stored prompts against a model endpoint: identical evidence, a different (or the same) model. Used to compare the local 7B with a larger local model without any
difference in retrieval, routing or building: every request is rebuilt exactly from a stored run (persona prompt, action boundary, dated context message, the stored evidence message,
the question), sent at temperature 0 with the same seed, and scored by the same scorer.

    python replay.py --run results/dev5-1500-a.json --conditions b1a+routed --out results/dev5-replay-7b.json                      # control: the production 7B
    python replay.py --run results/dev5-1500-a.json --conditions b1a+routed --model Qwen3-14B-AWQ --base-url http://localhost:8003  # a larger model, when one is served

It never starts, stops or swaps a model server: the target must already be serving. Loading a larger model on the production GPU is a separate, owner-approved operation (the model manager)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aq import cases as caselib
from aq import llm as llmlib
from aq.conditions import base_messages
from aq.scoring_v2 import score_answer


def rebuild(case: dict, context_text: str, builder_condition: bool) -> list[dict]:
    messages = base_messages(case)
    if builder_condition and context_text:
        messages.insert(len(messages) - 1, {"role": "user", "content": context_text})
    return messages


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True)
    p.add_argument("--conditions", default="b1a+routed")
    p.add_argument("--model")
    p.add_argument("--base-url")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    if a.model:
        llmlib.MODEL = a.model
    if a.base_url:
        llmlib.BASE = a.base_url
    llm = llmlib.Local()
    llm.client.base_url = llmlib.BASE  # the module-level default was read at import time
    if not llm.healthy():
        raise SystemExit("the model server is not healthy")
    run = json.loads(Path(a.run).read_text())
    cases = {c["id"]: c for c in caselib.load_cases(run["split"])}
    wanted = set(a.conditions.split(","))
    out, same, total = [], 0, 0
    for row in run["rows"]:
        if row["condition"] not in wanted or row["id"] not in cases:
            continue
        case = cases[row["id"]]
        text = row["context"].get("text", "")
        builder = bool(row["context"]["entries"])
        messages = rebuild(case, text, builder)
        done = llm.complete(messages, max_tokens=150 if case["modality"] == "voice" else 350)
        ctx = {"entries": row["context"]["entries"], "has_ids": builder, "text": text, "prompt_violations": row["score"]["privacy"]["rule_violations_in_prompt"]}
        score = score_answer(case, done.text, ctx)
        total += 1
        same += done.text == row["reply"]
        out.append({"id": row["id"], "condition": row["condition"], "model": llmlib.MODEL, "reply": done.text, "same_as_stored": done.text == row["reply"], "score": score,
                    "cost": {"ttft_ms": round(done.ttft_ms, 1), "total_ms": round(done.total_ms, 1), "prompt_tokens": done.prompt_tokens, "completion_tokens": done.completion_tokens}})
        print(f"{row['id']:6} {row['condition']:12} {score['correctness']:7} same={done.text == row['reply']}", file=sys.stderr, flush=True)
    Path(a.out).write_text(json.dumps({"source_run": Path(a.run).name, "model": llmlib.MODEL, "replayed": total, "identical_to_stored": same, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": out}, indent=1) + "\n")
    print(json.dumps({"model": llmlib.MODEL, "replayed": total, "identical_to_stored": same, "full": sum(r["score"]["correctness"] == "full" for r in out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
