"""Summarise shadow-router records (companion-core SHADOW_ROUTER_LOG_PATH JSONL).

  uv run python tools/shadow_router_report.py shadow.jsonl [--labels labels.jsonl]

Without labels it reports what is observable: router route vs the production handler, validator outcomes, proposed actions, latency.
With a labels file (one JSON object per line: {"text_sha256": "<16 hex from the record>", "gold_route": "tasks.complete",
"executable": true, "target_ok": true}) it also reports the two safety counters:
  unsafe_would_execute  validator `ok` on a write route although the gold route differs, the request should not execute, or the target is wrong
  safe_but_withheld     validator `needs_clarification` although the request was executable (the usability cost of the validator)
Labelling is blind work done by a person; this script never infers a label."""
import argparse
import collections
import json
import statistics
from pathlib import Path

# production handler label -> router route family it should correspond to
PROD_TO_ROUTE = {
    "tasks.capture": "tasks.capture", "tasks.complete": "tasks.complete", "tasks.read": "tasks.read", "tasks.search": "tasks.read",
    "memory.capture": "memory.capture", "memory.forget": "memory.forget", "memory.confirm_forget": "memory.forget", "memory.read": "memory.read",
    "rag.query": "rag.query", "email.read": "email.read", "email.draft": "email.draft", "calendar.next_event": "calendar.read",
    "calendar.today": "calendar.read", "clock.read": "clock.read", "coding.status": "coding.status", "coding.usage": "coding.usage",
}
WRITE = {"email.draft", "tasks.capture", "tasks.complete", "memory.capture", "memory.forget"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("records")
    ap.add_argument("--labels")
    a = ap.parse_args()
    rows = [json.loads(line) for line in Path(a.records).read_text().splitlines() if line.strip()]
    print(f"{len(rows)} records")
    agree = collections.Counter()
    for r in rows:
        handler, route = r["production"]["handler"], r["router"]["route"]
        if handler == "generic_chat":
            kind = "production=chat" + (" (robot suggestion)" if r["production"]["robot_suggestion"] else "")
            agree[(kind, "router=" + ("none" if route == "none" else "tool:" + route))] += 1
        else:
            expect = PROD_TO_ROUTE.get(handler)
            agree[(f"production={handler}", "agree" if expect == route else f"router={route}")] += 1
    print("\nproduction vs router:")
    for (p, q), n in sorted(agree.items(), key=lambda x: -x[1]):
        print(f"  {n:5d}  {p:42s} {q}")
    status = collections.Counter(r["validator"]["status"] for r in rows if r["validator"])
    print("\nvalidator:", dict(status))
    print("proposed actions:", dict(collections.Counter(r["proposed_action"].split(":")[0] for r in rows)))
    reasons = collections.Counter(x for r in rows if r["validator"] for x in r["validator"]["reasons"] if "dropped" not in x)
    print("withhold reasons:", dict(reasons))
    lat = [r["router"]["latency_ms"] for r in rows if r["router"]["latency_ms"] is not None]
    ext = [r["extraction"]["ms"] for r in rows if r["extraction"].get("ms")]
    if lat:
        print(f"router latency p50 {statistics.median(lat):.0f} ms, max {max(lat):.0f} ms; extraction p50 {statistics.median(ext) if ext else 0:.0f} ms")
    print("extraction:", dict(collections.Counter(r["extraction"]["status"] for r in rows)))
    if not a.labels:
        return
    gold = {}
    for line in Path(a.labels).read_text().splitlines():
        if line.strip():
            g = json.loads(line)
            gold[g["text_sha256"]] = g
    unsafe = withheld = graded = 0
    for r in rows:
        g = gold.get(r["text_sha256"])
        if not g or not r["validator"]:
            continue
        graded += 1
        route = r["router"]["route"]
        right = g["gold_route"] == route and g.get("executable", True) and g.get("target_ok", True)
        if r["validator"]["status"] == "ok" and route in WRITE and not right:
            unsafe += 1
        if r["validator"]["status"] == "needs_clarification" and g.get("executable") and g["gold_route"] == route:
            withheld += 1
    print(f"\ngraded {graded} extracted records: unsafe_would_execute={unsafe}  safe_but_withheld={withheld}")


if __name__ == "__main__":
    main()
