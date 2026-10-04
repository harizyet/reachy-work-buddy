"""Blind grading helpers for the shadow-router trial (docs/shadow-router.md#trial-procedure).

  sheet  LOG --out sheet.jsonl [--agree-sample 50] [--seed 1]
         Writes the items to label: EVERY record where the router and production disagree, plus a random sample of agreements, shuffled,
         showing only the utterance. No router, validator or production output is on the sheet.
  purge  LOG --labels labels.jsonl --aggregates out.json [--delete SHEET ...]
         Writes aggregates (counts, the graded labels without text) and then rewrites LOG in place with the utterance, its hash, validated args
         and resolved target removed (mode 0600 kept). Delete the sheet files too with --delete.

Label each sheet item by adding: "gold_route" (one of the 18 routes), "executable" (true if a correct system would act on it now), and
"gold_args" ({"task": "..."} the target as the user stated it; null for a field the user did not state). Then run shadow_router_report.py --labels."""
import argparse
import json
import os
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from shadow_router_report import is_disagreement

ROUTES = ["none", "unsupported", "calendar.read", "email.read", "email.draft", "tasks.read", "tasks.capture", "tasks.complete", "memory.read",
          "memory.capture", "memory.forget", "rag.query", "web.search", "coding.status", "coding.usage", "robot.standby", "robot.resume", "clock.read"]


def read_rows(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def sheet(a: argparse.Namespace) -> None:
    rows = [r for r in read_rows(a.log) if r.get("text")]
    seen: set[str] = set()
    unique = []
    for r in rows:  # one item per distinct utterance
        if r["text_sha256"] not in seen:
            seen.add(r["text_sha256"])
            unique.append(r)
    dis = [r for r in unique if is_disagreement(r)]
    agree = [r for r in unique if not is_disagreement(r)]
    rng = random.Random(a.seed)
    picked = dis + rng.sample(agree, min(a.agree_sample, len(agree)))
    rng.shuffle(picked)
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        for r in picked:
            handle.write(json.dumps({"text_sha256": r["text_sha256"], "text": r["text"], "gold_route": None, "executable": None, "gold_args": None}) + "\n")
    print(f"{len(picked)} items ({len(dis)} disagreements + {len(picked) - len(dis)} sampled of {len(agree)} agreements); routes: {', '.join(ROUTES)}")


def purge(a: argparse.Namespace) -> None:
    rows = read_rows(a.log)
    labels = [json.loads(line) for line in Path(a.labels).read_text().splitlines() if line.strip()]
    # gold labels keep route/executable only; hashes of short utterances can be guessed by dictionary, so they go too
    agg = {"records": len(rows), "labels": [{k: v for k, v in g.items() if k not in ("text", "text_sha256", "gold_args")} for g in labels]}
    fd = os.open(a.aggregates, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(agg, handle, indent=1)
    scrubbed = [{k: v for k, v in r.items() if k not in ("text", "validated_args", "resolved_target", "text_sha256")} for r in rows]
    tmp_fd, tmp_name = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(a.log)))  # mkstemp creates the file mode 0600
    with os.fdopen(tmp_fd, "w") as tmp:
        for r in scrubbed:
            tmp.write(json.dumps(r) + "\n")
    os.replace(tmp_name, a.log)
    for path in a.delete or []:
        Path(path).unlink(missing_ok=True)
    print(f"scrubbed {len(rows)} records (text, hashes, validated args, resolved targets removed); aggregates -> {a.aggregates}; deleted {len(a.delete or [])} file(s)")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("log")
    s.add_argument("--out", required=True)
    s.add_argument("--agree-sample", type=int, default=50)
    s.add_argument("--seed", type=int, default=1)
    p = sub.add_parser("purge")
    p.add_argument("log")
    p.add_argument("--labels", required=True)
    p.add_argument("--aggregates", required=True)
    p.add_argument("--delete", nargs="*")
    a = ap.parse_args()
    sheet(a) if a.cmd == "sheet" else purge(a)


if __name__ == "__main__":
    main()
