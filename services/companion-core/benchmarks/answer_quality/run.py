"""Run the answer-quality evaluation with the local 7B against a scratch Postgres (KBENCH_DATABASE_URL; disposable).

    python run.py --validate-only
    python run.py --split dev --conditions none,p43,b1a,b1b,oracle,distractor --budget 1500 --out results/dev-1500.json
    python run.py --split holdout --decision-point 44E-first-look   # refused unless AQ_HOLDOUT_APPROVAL names the decision point

Every run uses the invented corpus only. It calls the production vLLM, serially, and stops on a stop file, an unhealthy model server or the time cap."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aq import cases as caselib
from aq import llm as llmlib
from aq.conditions import CONDITIONS, Conditions
from aq.scoring import score_answer as score_v1
from aq.scoring_v2 import score_answer as score_v2

STOP_FILE = HERE / "STOP"
HOLDOUT_LOG = HERE / "holdout_runs.jsonl"
DEV8_LOG = HERE / "dev8_runs.jsonl"


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=HERE, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def check_holdout(decision_point: str | None, hashes: dict, conditions: list[str], budget: int) -> None:
    if not decision_point:
        raise SystemExit("scoring the holdout needs --decision-point NAME")
    if os.environ.get("AQ_HOLDOUT_APPROVAL") != decision_point:
        raise SystemExit("the holdout is scored only after the owner has reviewed its composition, labels, scoring and locked configuration: "
                         "set AQ_HOLDOUT_APPROVAL to the approved decision point name")
    if HOLDOUT_LOG.exists():
        for line in HOLDOUT_LOG.read_text().splitlines():
            e = json.loads(line)
            if e["decision_point"] == decision_point and e["combined_hash"] == hashes["combined"]:
                raise SystemExit(f"decision point {decision_point!r} was already scored on these fixtures ({e['at']}); a decision point gets one look")


def check_dev8(decision_point: str | None, hashes: dict) -> None:
    """dev8 is the untouched one-shot acceptance set for the frozen evidence-coverage mechanism: it is scored once, after an explicit approval, against the frozen files in dev8_freeze.json."""
    if not decision_point:
        raise SystemExit("scoring dev8 needs --decision-point NAME")
    if os.environ.get("AQ_DEV8_APPROVAL") != decision_point:
        raise SystemExit("dev8 is evaluated once, after the owner approves the protocol: set AQ_DEV8_APPROVAL to the approved decision point name")
    from freeze_check import verify

    problems = verify()
    if problems:
        raise SystemExit("the frozen files changed since dev8 was frozen: " + "; ".join(problems))
    if DEV8_LOG.exists():
        for line in DEV8_LOG.read_text().splitlines():
            e = json.loads(line)
            raise SystemExit(f"dev8 was already evaluated ({e['at']}, decision point {e['decision_point']!r}); it gets one look")


async def run(args) -> dict:
    from kbench.corpus import build_corpus
    from kbench.pg_env import build_pg_corpus

    llm = llmlib.Local()
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
    runner = Conditions(env, spec, llm, budget=args.budget, minilm_embed=embeddings.embed, flag_instructions=not args.no_instruction_flag)
    started, rows = time.monotonic(), []
    try:
        for case in cases:
            for name in conditions:
                if STOP_FILE.exists() or time.monotonic() - started > args.time_cap:
                    raise SystemExit("stopped: stop file or time cap")
                if not llm.healthy():
                    raise SystemExit("stopped: the model server became unhealthy")
                prep = await runner.prepare(name, case)
                if prep.skipped:
                    continue
                if prep.fixed_reply is not None:  # a deterministic reply: no model call, zero model latency
                    done = llmlib.Completion(prep.fixed_reply, 0.0, 0.0, 0, 0, "fixed")
                else:
                    done = llm.complete(prep.messages, max_tokens=150 if case["modality"] == "voice" else 350)
                scored = (score_v1 if args.scorer == "v1" else score_v2)(case, done.text, {
                    "entries": prep.entries, "has_ids": prep.has_ids, "text": prep.text, "prompt_violations": prep.prompt_violations,
                })
                rows.append({
                    "id": case["id"], "category": case["category"], "condition": name, "reply": done.text, "score": scored,
                    "cost": {
                        "retrieval_ms": round(prep.retrieval_ms, 1), "build_ms": round(prep.build_ms, 2), "ttft_ms": round(done.ttft_ms, 1),
                        "total_ms": round(done.total_ms, 1), "prompt_tokens": done.prompt_tokens, "completion_tokens": done.completion_tokens,
                        "evidence_tokens": prep.rendered.tokens if prep.rendered else (llm.count_tokens(prep.text) if prep.text else 0),
                        "finish": done.finish_reason,
                    },
                    "suff": prep.suff or None,
                    "context": {"text": prep.text, "entries": prep.entries, "dropped": prep.dropped, "retrieval_dropped": prep.retrieval_dropped, "candidates": prep.candidates,
                                "local_only": prep.rendered.local_only if prep.rendered else None,
                                "max_sensitivity": prep.rendered.max_sensitivity.value if prep.rendered else None},
                })
                print(f"{case['id']:6} {name:10} {scored['correctness']:7} {done.total_ms:6.0f} ms", file=sys.stderr, flush=True)
    finally:
        await env.close()
    hashes = caselib.case_hashes()
    return {
        "split": args.split, "conditions": conditions, "budget": args.budget, "instruction_flag": not args.no_instruction_flag, "scorer": args.scorer, "decision_point": args.decision_point, "hashes": hashes,
        "model": llmlib.MODEL, "seed": llmlib.SEED, "git_commit": git_commit(), "load_avg_start": os.getloadavg()[0],
        "at": datetime.now(UTC).isoformat(timespec="seconds"), "wall_seconds": round(time.monotonic() - started, 1), "rows": rows,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--split", choices=("dev", "dev2", "dev3", "dev4", "dev5", "dev6", "dev7", "dev8", "holdout"), default="dev")
    p.add_argument("--conditions", default=",".join(CONDITIONS))
    p.add_argument("--budget", type=int, default=1500, choices=(500, 1000, 1500))
    p.add_argument("--decision-point")
    p.add_argument("--no-instruction-flag", action="store_true", help="ablation: do not label instruction-like passages")
    p.add_argument("--scorer", choices=("v1", "v2"), default="v2", help="v1 reproduces the first-look scoring; v2 (default) has the 2026-10-09 corrections")
    p.add_argument("--only", help="comma-separated case ids")
    p.add_argument("--out")
    p.add_argument("--time-cap", type=float, default=2400.0)
    p.add_argument("--validate-only", action="store_true")
    args = p.parse_args()
    problems = caselib.validate()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    if args.validate_only:
        print("cases valid", json.dumps(caselib.case_hashes(), indent=1))
        return 0
    if args.split == "holdout":
        check_holdout(args.decision_point, caselib.case_hashes(), args.conditions.split(","), args.budget)
    if args.split == "dev8":
        check_dev8(args.decision_point, caselib.case_hashes())
    report = asyncio.run(run(args))
    if args.split == "dev8":
        with DEV8_LOG.open("a") as log:
            log.write(json.dumps({"decision_point": args.decision_point, "cases_sha256": report["hashes"]["dev8"], "conditions": report["conditions"], "git_commit": report["git_commit"], "at": report["at"]}) + "\n")
    if args.split == "holdout":
        with HOLDOUT_LOG.open("a") as log:
            log.write(json.dumps({"decision_point": args.decision_point, "combined_hash": report["hashes"]["combined"],
                                  "conditions": report["conditions"], "budget": args.budget, "git_commit": report["git_commit"],
                                  "at": report["at"]}) + "\n")
    text = json.dumps(report, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
