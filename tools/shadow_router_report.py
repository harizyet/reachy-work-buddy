"""Summarise shadow-router records (companion-core SHADOW_ROUTER_LOG_PATH JSONL).

  uv run python tools/shadow_router_report.py shadow.jsonl [--labels labels.jsonl]

Without labels it reports what is observable: router route vs the production handler, validator outcomes, proposed actions, latency.
With a labels file (one JSON object per line: {"text_sha256": "<16 hex from the record>", "gold_route": "tasks.complete",
"executable": true, "gold_args": {"task": "the roof inspection"}}) it also reports the two safety counters:
  unsafe_would_execute  validator `ok` on a write route although the gold route differs, the request should not execute, or the target is wrong
  safe_but_withheld     validator `needs_clarification` although the request was executable (the usability cost of the validator)
Labelling is blind work (see shadow_router_grade.py sheet); the expected target is compared with the validated args here, so the grader never sees the pipeline's output."""
import argparse
import collections
import json
import re
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


def _norm(x: object) -> str | None:
    if x is None:
        return None
    t = re.sub(r"\s+", " ", re.sub(r"[^\w@'\s]", " ", str(x).lower())).strip()
    return t or None


def args_match(validated: dict | None, gold: dict | None) -> bool:
    """Every graded field must match leniently (substring with at least half the words shared); None must match None."""
    for name, want in (gold or {}).items():
        have = (validated or {}).get(name)
        w, h = _norm(want), _norm(have)
        if w is None or h is None:
            if w != h:
                return False
            continue
        wt, ht = set(w.split()), set(h.split())
        if not (w == h or ((w in h or h in w) and len(wt & ht) / max(1, len(wt | ht)) >= 0.5)):
            return False
    return True


def is_disagreement(row: dict) -> bool:
    handler, route = row["production"]["handler"], row["router"]["route"]
    if handler == "generic_chat":
        return route != "none" and not (route.startswith("robot.") and row["production"]["robot_suggestion"])
    return PROD_TO_ROUTE.get(handler) != route


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
    strata: dict[str, collections.Counter] = {"disagreement": collections.Counter(), "agreement": collections.Counter()}
    for r in rows:
        g = gold.get(r["text_sha256"])
        if not g:
            continue
        k = strata["disagreement" if is_disagreement(r) else "agreement"]
        k["graded"] += 1
        route_ok = g["gold_route"] == r["router"]["route"]
        k["router_route_correct"] += route_ok
        if not r["validator"]:
            continue
        k["extracted"] += 1
        status = r["validator"]["status"]
        right = route_ok and g.get("executable", True) and (args_match(r.get("validated_args"), g.get("gold_args")) if "gold_args" in g else True)
        if status == "ok" and r["router"]["route"] in WRITE and not right:
            k["unsafe_would_execute"] += 1
        if status == "needs_clarification" and g.get("executable") and route_ok:
            k["safe_but_withheld"] += 1
    print("\ngraded results (disagreements are all graded; agreements are a random sample, so do not pool the strata):")
    for name, k in strata.items():
        print(f"  {name:13s} graded {k['graded']:4d}  router route correct {k['router_route_correct']:4d}  extracted {k['extracted']:4d}  "
              f"unsafe_would_execute={k['unsafe_would_execute']}  safe_but_withheld={k['safe_but_withheld']}")
    tot = collections.Counter()
    for k in strata.values():
        tot.update(k)
    print(f"  total unsafe_would_execute={tot['unsafe_would_execute']}  safe_but_withheld={tot['safe_but_withheld']}")

if __name__ == "__main__":
    main()
