"""Generate the 7B replies for the formal validation plan (owner-approved 2026-10-16): isolated scratch infrastructure (throwaway Postgres on a loopback port), invented data, the production-model server used
as a plain inference endpoint, nothing scored here. State guard: needs 'frozen'; moves to 'generated'. `--dry-run` builds each world and prepares the first item WITHOUT calling the model and writes nothing.

    KBENCH_DATABASE_URL=<scratch> python acceptance_generate.py [--worlds 31,32] [--dry-run]"""
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
sys.path.insert(0, str(AQ.parent / "knowledge_retrieval"))
import acceptance_config as cfg
import acceptance_state as st
import fresh_v5_manifest as fm
import httpx
from aq import cases as _cases  # noqa: F401
from aq import llm as llmlib
from aq.conditions_g2 import GConditions2

PLAN = HERE / "acceptance" / "plan.json"
OUT = HERE / "acceptance" / "replies.jsonl"


def complete(llm, messages, temperature, seed):
    body = {"model": llmlib.MODEL, "messages": messages, "temperature": temperature, "seed": seed, "max_tokens": 350}
    r = llm.client.post("/v1/chat/completions", json=body)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


async def main(worlds: list[int], dry: bool, plan_path: Path = PLAN):
    from companion_core.rag import embeddings
    from kbench.corpus import build_corpus
    from kbench.pg_env import build_pg_corpus
    from validate_scorer import PEOPLE

    if not dry and plan_path == PLAN:
        st.require("frozen")
    plan = json.loads(plan_path.read_text())
    llm = llmlib.Local()
    if not dry and not llm.healthy():
        raise SystemExit("the model server is not healthy")
    embeddings.embed(["warm up"])
    done = {json.loads(x)["key"] for x in OUT.read_text().splitlines()} if (OUT.exists() and not dry) else set()
    by_world: dict[int, list] = {}
    for seq_name, seq in plan["sequences"].items():
        pop, cat = seq_name.split("|")
        for it in seq:
            if it["world"] in worlds:
                by_world.setdefault(it["world"], []).append({**it, "population": pop, "category": cat})
    t0 = time.monotonic()
    for w in worlds:
        corpus, _, cases = fm.world(w)
        tmp = HERE / "acceptance" / f"_corpus_w{w}.json"
        tmp.write_text(json.dumps(corpus))
        os.environ["KBENCH_CORPUS"] = str(tmp)
        case_by_id = {c["id"]: c for c in cases}
        spec = (await build_corpus()).spec
        env = await build_pg_corpus(spec, embeddings.embed, embeddings._MODEL_NAME)
        runner = GConditions2(env, spec, llm, budget=1500, minilm_embed=embeddings.embed)
        runner.people = PEOPLE
        try:
            items = [i for i in by_world.get(w, []) if i["key"] not in done]
            if dry:
                items = items[:1]
            for it in items:
                case = case_by_id[it["case"]]
                prep = await runner.prepare(it["arm"], case)
                if dry:
                    print("dry-run ok", w, it["key"], it["arm"], len(prep.messages))
                    continue
                manifest = {eid: {"refs": list(e.refs), "authorized": e.authorized} for eid, e in prep.evidence.items()}
                _name, temp, seed, extra = next((c[0], c[1], c[2], c[3]) for c in cfg.CONFIGS[it["population"]] if c[0] == it["config"])
                messages = [dict(m) for m in prep.messages]
                if extra:
                    messages[-1] = {**messages[-1], "content": messages[-1]["content"] + "\n\n" + extra}
                try:
                    reply = complete(llm, messages, temp, seed)
                except httpx.HTTPError as exc:
                    print("model error", type(exc).__name__, file=sys.stderr, flush=True)
                    continue
                with OUT.open("a") as fh:
                    fh.write(json.dumps({**it, "question": case["question"], "reply": reply, "manifest": manifest}) + "\n")
        finally:
            await env.close()
            tmp.unlink(missing_ok=True)
        print(f"world {w} done {round(time.monotonic() - t0)}s", file=sys.stderr, flush=True)
    if not dry and plan_path == PLAN:
        have = {json.loads(x)["key"] for x in OUT.read_text().splitlines()}
        want = {it["key"] for seq in plan["sequences"].values() for it in seq}
        if want <= have:
            st.advance("generated", replies_sha256=st.sha(OUT), replies=len(have))
        else:
            print(f"{len(want - have)} planned replies are still missing; rerun to resume", file=sys.stderr)


if __name__ == "__main__":
    for var in ("KBENCH_DATABASE_URL",):
        if not os.environ.get(var):
            raise SystemExit(f"set {var}")
    worlds = cfg.WORLDS
    if "--worlds" in sys.argv:
        worlds = [int(x) for x in sys.argv[sys.argv.index("--worlds") + 1].split(",")]
    asyncio.run(main(worlds, "--dry-run" in sys.argv))
