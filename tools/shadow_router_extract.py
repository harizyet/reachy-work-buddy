"""Offline extraction for the shadow-router trial (docs/shadow-router.md#trial-procedure).

  uv run --package companion-core python tools/shadow_router_extract.py shadow.jsonl --out extractions.jsonl --base-url http://localhost:8003/v1 --model Qwen/Qwen2.5-7B-Instruct-AWQ

Runs the SAME frozen few-shot extractor and deterministic validator the live mode uses, over records the live path marked `extraction: pending`
(it needs the utterance, so the trial must have run with SHADOW_ROUTER_LOG_TEXT=true). One request at a time, so run it when the 7B is idle.
The raw log is never modified: results go to a separate 0600 file keyed by `rid`, which shadow_router_report.py --extractions merges."""
import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from companion_core.shadow_router import validator
from companion_core.shadow_router.extractor import extract
from companion_core.shadow_router.shadow import (
    _RETAIN_TARGET,
    ShadowPipeline,
    _category,
)

from shared.models.llm import ProviderConfig


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key-env", help="name of an environment variable holding the key (never pass a key on the command line)")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    provider = ProviderConfig(base_url=a.base_url, model=a.model, api_key=os.environ.get(a.api_key_env) if a.api_key_env else None)
    rows = [json.loads(line) for line in Path(a.log).read_text().splitlines() if line.strip()]
    pending = [r for r in rows if r.get("extraction", {}).get("status") == "pending"]
    todo = [r for r in pending if r.get("text")]
    if a.limit:
        todo = todo[: a.limit]
    done: dict[str, dict] = {}
    if Path(a.out).exists():  # resumable: skip records already extracted OK (errors are retried; the merge keeps the last row per rid)
        done = {x["rid"]: 1 for x in (json.loads(line) for line in Path(a.out).read_text().splitlines() if line.strip()) if x["extraction"]["status"] == "ok"}
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    n = errors = 0
    with os.fdopen(fd, "a") as out:
        for r in todo:
            if r["rid"] in done:
                continue
            route = r["router"]["route"]
            started = time.monotonic()
            proposed = await extract(provider, route, r["text"])
            ms = round((time.monotonic() - started) * 1000)
            verdict = validator.validate(route, proposed, r["text"]) if proposed is not None else None
            errors += proposed is None
            row = {
                "rid": r["rid"], "extraction": {"status": "ok" if proposed is not None else "error", "model": a.model, "ms": ms},
                "validator": None if verdict is None else {"status": verdict.status, "reasons": [_category(x) for x in verdict.reasons]},
                "proposed_action": ShadowPipeline._proposed_action(route, verdict),
            }
            if verdict is not None:
                row["validated_args"] = verdict.args
                if route in _RETAIN_TARGET and r.get("privacy") != "sensitive":
                    row["resolved_target"] = verdict.args.get(_RETAIN_TARGET[route])
            out.write(json.dumps(row) + "\n")
            out.flush()
            n += 1
    print(f"{len(pending)} pending records, {len(todo)} with text; extracted {n} now ({errors} extractor errors); {len(pending) - len(todo)} skipped (no text)")


if __name__ == "__main__":
    asyncio.run(main())
