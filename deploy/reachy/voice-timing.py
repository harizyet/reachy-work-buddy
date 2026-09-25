"""Per-turn voice latency from reachy-embodiment's log (Phase 24d/24e timing).

Reads the embodiment log (for example `docker logs reachy-embodiment 2>&1`)
on stdin and prints, per turn: utterance end -> first audible reply, using
the timing sources agreed in 24d
(docs/verification/phase-24d-conversation-2026-09-24.md):

- utterance end = the turn's last "utterance cut" log time minus the
  end-of-speech window (0.7 s by default);
- first audible = "voice playback started" (the daemon accepted
  play_sound; a lower bound, since daemon start-up latency is unmeasured).

A held turn (24e adaptive end of turn) is timed from its last segment's
cut, so it includes the continuation window, as the budget intends.
Search turns come from the owner GUI's search log and are passed with
`--search-turns`; they get the per-turn cap instead of p50/p95.

Budgets (agreed 2026-09-24/25): non-search p50 <= 4 s and p95 <= 8 s,
nearest rank; each search turn <= 20 s. Read-only: it only parses text.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from datetime import datetime, timezone

TS = r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
CUT = re.compile(
    TS
    + r".*voice turn (?P<turn>\d+)\.(?P<seg>\d+): utterance cut \((?P<secs>[\d.]+)s of audio\)"
)
REPLY = re.compile(
    TS + r".*voice turn (?P<turn>\d+)\.(?P<seg>\d+): hub replied (?P<outcome>\w+) after"
)
FINAL = re.compile(
    TS
    + r".*voice turn (?P<turn>\d+): finalized after (?P<segs>\d+) segments, hub replied (?P<outcome>\w+)"
)
PLAY = re.compile(TS + r".*voice playback started \((?P<secs>[\d.]+)s of audio\)")
PALM = re.compile(TS + r".*voice turn (?P<turn>\d+): reply stopped by open palm")
START = re.compile(TS + r".*voice start received")


def parse_ts(text: str) -> datetime:
    # The container logs in UTC; only differences between lines are used.
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=timezone.utc)  # noqa: UP017 - runs on the Nano's Python 3.10


def nearest_rank(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--search-turns", default="", help="comma-separated turn numbers that searched"
    )
    parser.add_argument(
        "--eos-seconds",
        type=float,
        default=0.7,
        help="end-of-speech window (VoiceLimits)",
    )
    parser.add_argument(
        "--since",
        help="only lines at or after this log time (UTC), 'YYYY-MM-DD HH:MM:SS'",
    )
    parser.add_argument(
        "--session",
        type=int,
        default=-1,
        help="which voice session in the log (default: last)",
    )
    args = parser.parse_args()
    search = {int(t) for t in args.search_turns.split(",") if t.strip()}
    since = None
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)  # noqa: UP017

    # Lines before any "voice start received" (e.g. cut off by --since)
    # count as one session.
    turns: dict[int, dict] = {}
    sessions: list[dict] = [turns]
    current: int | None = None  # turn whose reply is expected to play next
    for line in sys.stdin:
        if (
            since is not None
            and (m := re.match(TS, line))
            and parse_ts(m["ts"]) < since
        ):
            continue
        if START.match(line):
            if turns:
                turns = {}
                sessions.append(turns)
            current = None
        elif m := CUT.match(line):
            t = turns.setdefault(int(m["turn"]), {"segments": 0, "audio_s": 0.0})
            t["last_cut"] = parse_ts(m["ts"])
            t["segments"] = max(t["segments"], int(m["seg"]))
            t["audio_s"] += float(m["secs"])
        elif (m := REPLY.match(line)) or (m := FINAL.match(line)):
            t = turns.setdefault(int(m["turn"]), {"segments": 0, "audio_s": 0.0})
            t["outcome"] = m["outcome"]
            if m["outcome"] != "continue":
                current = int(m["turn"])
        elif (m := PLAY.match(line)) and current is not None and current in turns:
            turns[current]["played"] = parse_ts(m["ts"])
            turns[current]["reply_s"] = float(m["secs"])
            current = None
        elif m := PALM.match(line):
            turns.setdefault(int(m["turn"]), {})["palm_stop"] = True
    turns = sessions[args.session]
    if not turns:
        print("no voice turns found", file=sys.stderr)
        return 1

    print(
        "| Turn | Search | Segments | Audio (s) | Outcome | Utterance end -> first audio (s) | Reply audio (s) |"
    )
    print("|---|---|---|---|---|---|---|")
    plain, searched = [], []
    for number in sorted(turns):
        t = turns[number]
        latency = None
        if "played" in t and "last_cut" in t:
            end = t["last_cut"].timestamp() - args.eos_seconds
            latency = t["played"].timestamp() - end
            (searched if number in search else plain).append(latency)
        note = " (palm stop)" if t.get("palm_stop") else ""
        print(
            f"| {number} | {'yes' if number in search else '–'} | {t.get('segments', 0)} | "
            f"{t.get('audio_s', 0):.2f} | {t.get('outcome', '?')}{note} | "
            f"{'' if latency is None else f'{latency:.2f}'} | {t.get('reply_s', '')} |"
        )
    print()
    if plain:
        p50, p95 = nearest_rank(plain, 50), nearest_rank(plain, 95)
        verdict = "PASS" if p50 <= 4.0 and p95 <= 8.0 else "FAIL"
        print(
            f"Non-search ({len(plain)} spoken turns): p50 {p50:.2f} s, p95 {p95:.2f} s (nearest rank): {verdict}"
        )
    if searched:
        worst = max(searched)
        print(
            f"Search ({len(searched)} spoken turns): worst {worst:.2f} s: {'PASS' if worst <= 20.0 else 'FAIL'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
