#!/usr/bin/env python3
"""Phase 48B supervised capture trial: read-only counts from the homelab database. Never prints candidate text.

    python3 tools/memory_candidate_trial_report.py [--since 2026-10-10T14:00:00Z]

Durable counters are hourly rows (proposed, accepted, edited_accepted, rejected, suppressed, expired, forgotten).
Duplicate/exclusion/cap tallies exist only in core's in-memory summary, which is logged when core stops; read it from
`docker logs reachy-homelab-companion-core-1 | grep "capture summary"` after a graceful stop. Incorrect sensitivity or
scope and missed candidate-worthy facts are the owner's tally (docs/verification/phase-48b-capture-trial-2026-10-10.md).
"""

import argparse
import subprocess

PSQL = ["docker", "exec", "reachy-homelab-postgres-1", "psql", "-U", "reachy", "-d", "reachy_hub", "-A", "-F", "\t", "-c"]


def query(sql: str) -> str:
    return subprocess.run([*PSQL, sql], capture_output=True, text=True, check=True).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="1970-01-01T00:00:00Z")
    since = parser.parse_args().since
    safe = since.replace("'", "")
    print("-- durable counters since", since)
    print(query(f"SELECT kind, sum(n) AS n FROM memory_candidate_counters WHERE hour >= '{safe}' GROUP BY kind ORDER BY kind"))
    print("-- current candidate rows by status and channel (no text)")
    print(query("SELECT status, channel, count(*) FROM memory_candidates GROUP BY 1, 2 ORDER BY 1, 2"))
    print("-- suppression rules:", query("SELECT count(*) FROM memory_candidate_suppressions").splitlines()[-2])
    print("-- memories created from candidates (not forgotten):",
          query("SELECT count(*) FROM memories WHERE source LIKE 'candidate:%' AND forgotten_at IS NULL").splitlines()[-2])


if __name__ == "__main__":
    main()
