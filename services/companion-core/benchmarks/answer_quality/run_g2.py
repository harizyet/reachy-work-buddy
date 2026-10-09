"""Runner for the groundedness ablation (corpus v2). Same discipline as run.py: serial, 7B at temperature 0 with a fixed seed, scratch Postgres, scorer v2. Arms are condition strings such as
`b1a+routed`, `b1a+routed+c1f+c2t`, `b1a+routed+c4+c5`, `oracle+c4+c5`. dev12 is guarded like dev8 and dev10 (decision point, approval variable, frozen manifest, one run).

    KBENCH_CORPUS=corpus_v2/corpus_v2.json python run_g.py --split dev11 --conditions ... --out results/NAME.json"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "corpus_v3"))

import run as base_run
from aq import cases as caselib
from aq import llm as llmlib
from aq.conditions_g2 import GConditions2 as GConditions
from aq.llm_json import LocalJSON
from aq.scoring_v2 import score_answer
from companion_core.knowledge.grounding import claims as claimlib
from companion_core.knowledge.grounding import validate as validatelib
from gen import PEOPLE

_CITED = re.compile(r"\bE(\d+)\b")


def citation_audit(reply: str, evidence: dict) -> dict:
    ids = {f"E{m}" for m in _CITED.findall(reply)}
    bad_unknown = [i for i in ids if i not in evidence or not evidence[i].refs]
    bad_unauth = [i for i in ids if i in evidence and not evidence[i].authorized]
    return {"cited": sorted(ids), "nonexistent": bad_unknown, "unauthorized": bad_unauth}


async def run(args) -> dict:
    from kbench.corpus import build_corpus
    from kbench.pg_env import build_pg_corpus

    llm = LocalJSON()
    if not llm.healthy():
        raise SystemExit("the model server is not healthy")
    cases = caselib.load_cases(args.split)
    if args.only:
        cases = [c for c in cases if c["id"] in args.only.split(",")]
    conditions = args.conditions.split(",")
    spec = (await build_corpus()).spec
    from companion_core.rag import embeddings

    embeddings.embed(["warm up"])
    env = await build_pg_corpus(spec, embeddings.embed, embeddings._MODEL_NAME)
    runner = GConditions(env, spec, llm, budget=args.budget, minilm_embed=embeddings.embed)
    runner.people = PEOPLE
    rows = []
    started = time.monotonic()
    try:
        for case in cases:
            for name in conditions:
                if (base_run.STOP_FILE).exists() or time.monotonic() - started > args.time_cap:
                    raise SystemExit("stopped: stop file or time cap")
                t_prep = time.perf_counter()
                prep = await runner.prepare(name, case)
                prep_ms = (time.perf_counter() - t_prep) * 1000
                mods = set(prep.g_mods)
                gx = dict(prep.g)
                if prep.fixed_reply is not None:
                    done = llmlib.Completion(prep.fixed_reply, 0.0, 0.0, 0, 0, "fixed")
                elif "c4" in mods:
                    done = llm.complete_json(claimlib.with_instruction(prep.messages))
                    parsed = claimlib.parse(done.text)
                    gx["parse_ok"] = parsed is not None
                    cl, unknown = parsed if parsed else ([], [])
                    diag = validatelib.validate(cl, prep.evidence)
                    gx.update(claims=len(cl), valid_claims=len(diag.accepted), rejections=[r for _, r in diag.rejected])
                    used = diag.accepted if "c5" in mods else cl
                    dropped = len(cl) - len(used)
                    text = claimlib.render(used, unknown, dropped) if parsed is not None else "I couldn't produce an answer I can support from the records."
                    gx["accepted_invalid"] = (len(used) - len(diag.accepted)) if "c5" not in mods else 0
                    done = llmlib.Completion(text, done.ttft_ms, done.total_ms, done.prompt_tokens, done.completion_tokens, done.finish_reason)
                else:
                    done = llm.complete(prep.messages, max_tokens=350)
                scored = score_answer(case, done.text, {"entries": prep.entries, "has_ids": prep.has_ids, "text": prep.text, "prompt_violations": prep.prompt_violations})
                gx["citations"] = citation_audit(done.text, prep.evidence)
                rows.append({"id": case["id"], "category": case["category"], "label": case.get("label"), "condition": name, "reply": done.text, "score": scored, "g": gx,
                             "timings": {**{k: round(v, 2) for k, v in getattr(prep, "timings", {}).items()}, "prepare_total_ms": round(prep_ms, 1), "model_ms": round(done.total_ms, 1), "end_to_end_ms": round(prep_ms + done.total_ms, 1)},
                             "cost": {"retrieval_ms": round(prep.retrieval_ms, 1), "total_ms": round(done.total_ms, 1), "prompt_tokens": done.prompt_tokens, "completion_tokens": done.completion_tokens, "finish": done.finish_reason,
                                      "shown": len(prep.entries)},
                             "context": {"text": prep.text, "entries": prep.entries}})
                print(f"{case['id']:8} {name:28} {scored['correctness']:7} {done.total_ms:6.0f} ms", file=sys.stderr, flush=True)
    finally:
        await env.close()
    return {"split": args.split, "conditions": conditions, "budget": args.budget, "scorer": "v2", "model": llmlib.MODEL, "seed": llmlib.SEED, "git_commit": base_run.git_commit(), "hashes": caselib.case_hashes(),
            "at": datetime.now(UTC).isoformat(timespec="seconds"), "wall_seconds": round(time.monotonic() - started, 1), "rows": rows}


def check_dev14(decision_point):
    """dev14 is the one-shot acceptance set of the scoped readiness work: decision point, approval variable, frozen manifest present and unchanged, one run."""
    if not decision_point:
        raise SystemExit("scoring dev14 needs --decision-point NAME")
    if os.environ.get("AQ_DEV14_APPROVAL") != decision_point:
        raise SystemExit("dev14 is evaluated once, after the owner approves: set AQ_DEV14_APPROVAL to the approved decision point name")
    if not (HERE / "dev14_freeze.json").exists():
        raise SystemExit("dev14 has not been frozen yet (dev14_freeze.json is missing)")
    from freeze_check import verify

    problems = verify("dev14_freeze.json")
    if problems:
        raise SystemExit("the frozen files changed since dev14 was frozen: " + "; ".join(problems))
    log = HERE / "dev14_runs.jsonl"
    if log.exists() and log.read_text().strip():
        e = json.loads(log.read_text().splitlines()[0])
        raise SystemExit(f"dev14 was already evaluated ({e['at']}, decision point {e['decision_point']!r}); it gets one look")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--split", choices=("dev13", "dev14"), default="dev13")
    p.add_argument("--conditions", required=True)
    p.add_argument("--budget", type=int, default=1500)
    p.add_argument("--decision-point")
    p.add_argument("--only")
    p.add_argument("--out")
    p.add_argument("--time-cap", type=float, default=5400.0)
    args = p.parse_args()
    if not os.environ.get("KBENCH_CORPUS"):
        raise SystemExit("set KBENCH_CORPUS to corpus_v3/corpus_v3.json")
    problems = caselib.validate()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    if args.split == "dev14":
        check_dev14(args.decision_point)
    report = asyncio.run(run(args))
    if args.split == "dev14":
        with (HERE / "dev14_runs.jsonl").open("a") as log:
            log.write(json.dumps({"decision_point": args.decision_point, "conditions": report["conditions"], "git_commit": report["git_commit"], "at": report["at"]}) + "\n")
    text = json.dumps(report, indent=1)
    if args.out:
        Path(args.out).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
