"""Pilot: the production 7B answers the Stage A design questions (dev15) with baseline B1a evidence and with oracle (gold) evidence; the replies are scored by the sub-claim scorer. Used ONLY to validate the
scorer on real model output and to build the failure taxonomy; it is not an evaluation of any mechanism. No response policy is changed."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
AQ = HERE.parent
sys.path.insert(0, str(AQ))
sys.path.insert(0, str(HERE))
import scorer
from aq import cases as _cases  # noqa: F401
from aq import llm as llmlib
from aq.conditions_g2 import GConditions2
from validate_scorer import PEOPLE


async def main(split: str, out: str, arms: list[str]):
    from companion_core.rag import embeddings
    from kbench.corpus import build_corpus
    from kbench.pg_env import build_pg_corpus

    llm = llmlib.Local()
    if not llm.healthy():
        raise SystemExit("the model server is not healthy")
    cases = json.loads((AQ / f"cases_{split}.json").read_text())["cases"]
    spec = (await build_corpus()).spec
    embeddings.embed(["warm up"])
    env = await build_pg_corpus(spec, embeddings.embed, embeddings._MODEL_NAME)
    runner = GConditions2(env, spec, llm, budget=1500, minilm_embed=embeddings.embed)
    runner.people = PEOPLE
    rows = []
    t0 = time.monotonic()
    try:
        for case in cases:
            for arm in arms:
                prep = await runner.prepare(arm, case)
                done = llm.complete(prep.messages, max_tokens=350)
                manifest = {eid: {"refs": list(e.refs), "authorized": e.authorized} for eid, e in prep.evidence.items()}
                o = scorer.score_question(done.text, case["atoms"], manifest, PEOPLE)
                rows.append({"id": case["id"], "family": case["family"], "arm": arm, "question": case["question"], "reply": done.text, "manifest": manifest, "outcome": json.loads(json.dumps(o, default=lambda x: x.__dict__)),
                             "ms": round(done.total_ms)})
                print(f"{case['id']} {arm} ok={o.fully_correct}", file=sys.stderr, flush=True)
    finally:
        await env.close()
    Path(out).write_text(json.dumps({"split": split, "arms": arms, "wall_seconds": round(time.monotonic() - t0), "rows": rows}, indent=1))


if __name__ == "__main__":
    if not os.environ.get("KBENCH_CORPUS"):
        raise SystemExit("set KBENCH_CORPUS to selective/corpus_v4.json")
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3].split(",")))
