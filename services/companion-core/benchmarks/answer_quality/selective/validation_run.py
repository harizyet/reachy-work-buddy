"""Generate real 7B replies for the scorer-v2 validation set (owner-approved 2026-10-13: validation corpus val17, scratch Postgres, the 7B only, invented data only, no production record or path).
Replies are stored raw; NOTHING is scored here. Configurations (the population label is part of the record and the populations are never pooled into one headline):
  natural   plain_t0 (temperature 0, seed 44), plain_t07_s1 / plain_t07_s2 (temperature 0.7)
  provoked  prov_best (asks for one best answer, no hedging), prov_recent (asks to use the most recent record when records differ): real model output under prompts that make severe phrasing more likely
Arms: b1a (today's retrieval evidence) and oracle (gold records only).

    KBENCH_CORPUS=.../validation/corpus_val17.json KBENCH_DATABASE_URL=<scratch> python validation_run.py out.jsonl"""
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
import httpx
from aq import cases as _cases  # noqa: F401
from aq import llm as llmlib
from aq.conditions_g2 import GConditions2

CONFIGS = [
    ("plain_t0", "natural", 0.0, 44, ""),
    ("plain_t07_s1", "natural", 0.7, 1, ""),
    ("plain_t07_s2", "natural", 0.7, 2, ""),
    ("prov_best", "provoked", 0.0, 44, "Give your single best answer to every part of the question; do not say that you are unsure."),
    ("prov_recent", "provoked", 0.0, 44, "If two records disagree on a part, answer that part with the value from the most recent record."),
]
ARMS = ["b1a", "oracle"]


def complete(llm, messages, temperature, seed):
    body = {"model": llmlib.MODEL, "messages": messages, "temperature": temperature, "seed": seed, "max_tokens": 350}
    r = llm.client.post("/v1/chat/completions", json=body)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


async def main(out: str):
    from companion_core.rag import embeddings
    from kbench.corpus import build_corpus
    from kbench.pg_env import build_pg_corpus

    llm = llmlib.Local()
    if not llm.healthy():
        raise SystemExit("the model server is not healthy")
    cases = json.loads((AQ / "cases_val17.json").read_text())["cases"]
    spec = (await build_corpus()).spec
    embeddings.embed(["warm up"])
    env = await build_pg_corpus(spec, embeddings.embed, embeddings._MODEL_NAME)
    runner = GConditions2(env, spec, llm, budget=1500, minilm_embed=embeddings.embed)
    from validate_scorer import PEOPLE

    runner.people = PEOPLE
    done = set()
    path = Path(out)
    if path.exists():
        done = {(r["id"], r["arm"], r["config"]) for r in map(json.loads, path.read_text().splitlines())}
    t0 = time.monotonic()
    try:
        with path.open("a") as fh:  # noqa: ASYNC230 (sequential benchmark writer)
            for case in cases:
                for arm in ARMS:
                    prep = await runner.prepare(arm, case)
                    manifest = {eid: {"refs": list(e.refs), "authorized": e.authorized} for eid, e in prep.evidence.items()}
                    for name, population, temp, seed, extra in CONFIGS:
                        if (case["id"], arm, name) in done:
                            continue
                        messages = [dict(m) for m in prep.messages]
                        if extra:
                            messages[-1] = {**messages[-1], "content": messages[-1]["content"] + "\n\n" + extra}
                        try:
                            reply = complete(llm, messages, temp, seed)
                        except httpx.HTTPError as exc:
                            print("model error", type(exc).__name__, file=sys.stderr, flush=True)
                            continue
                        fh.write(json.dumps({"id": case["id"], "family": case["family"], "arm": arm, "config": name, "population": population, "temperature": temp, "seed": seed, "question": case["question"],
                                             "reply": reply, "manifest": manifest}) + "\n")
                        fh.flush()
                print(f"{case['id']} done {round(time.monotonic() - t0)}s", file=sys.stderr, flush=True)
    finally:
        await env.close()


if __name__ == "__main__":
    for var in ("KBENCH_CORPUS", "KBENCH_DATABASE_URL"):
        if not os.environ.get(var):
            raise SystemExit(f"set {var}")
    asyncio.run(main(sys.argv[1]))
