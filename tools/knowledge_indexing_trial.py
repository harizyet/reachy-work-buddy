"""Supervised production indexing-workload trial: read-only preflight, bounded monitor with abort gates, and a post-trial source-consistency check.

Phase 44E gate: the real MiniLM load and the outbox claim, lease and complete path have never run on production. This tool never writes. It does not
insert into the outbox, create records, change a flag or restart a service: the owner makes one genuine write through an existing application path, and the
operator (a person) turns the indexing flag on and off with the compose commands in docs/verification/phase-44b-indexing-workload-trial-plan-2026-10-10.md.

  python tools/knowledge_indexing_trial.py preflight [--out FILE]         read-only checks; exit 0 only if every check passes
  python tools/knowledge_indexing_trial.py monitor --seconds 900 --log FILE   samples every few seconds, aborts on a gate, writes a TSV
  python tools/knowledge_indexing_trial.py watch --seconds 900 --log FILE     4 Hz view of the outbox and the newest index rows (one psql connection)
  python tools/knowledge_indexing_trial.py snapshot                            one-line counts: index rows by kind, outbox rows, connections
  python tools/knowledge_indexing_trial.py verify                              read-only drift check of the index against the stores (one-off container)

Everything reads the homelab compose project (reachy-homelab) through `docker exec`; no host database port is used and no credential is printed."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

PG, CORE, HUB, PGB = "reachy-homelab-postgres-1", "reachy-homelab-companion-core-1", "reachy-homelab-reachy-hub-1", "reachy-homelab-pgbouncer-1"
VLLM_HEALTH = "http://localhost:8003/health"
REQUIRED_REVISION = "027_knowledge_index"
# Mandatory abort gates (the 44B contention and trial limits, plus the Phase 45 PgBouncer limits).
GATES = {"pg_connections": 85, "waiting_samples": 3, "maxwait_s": 2, "health_ms": 3000, "load": 14.0, "min_available_mb": 3000}

PGB_SCRIPT = (
    "import os,sys,psycopg;u=os.environ['DATABASE_URL'].rsplit('/',1)[0]+'/pgbouncer'\n"
    "with psycopg.connect(u,autocommit=True,prepare_threshold=None) as c:\n"
    " cur=c.execute('SHOW POOLS');cols=[d.name for d in cur.description]\n"
    " for r in cur.fetchall():\n"
    "  d=dict(zip(cols,r))\n"
    "  if d['database']=='reachy_hub': print(d['cl_active'],d['cl_waiting'],d['sv_active'],d['sv_idle'],d['maxwait'])\n"
)
HEALTH_SCRIPT = "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/health',timeout=4).status)"


def sh(*args: str, timeout: float = 30.0) -> str:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False).stdout.strip()


def psql(sql: str) -> str:
    return sh("docker", "exec", PG, "psql", "-U", "reachy", "-d", "reachy_hub", "-At", "-F", ",", "-c", sql)


def core_python(code: str) -> str:
    return sh("docker", "exec", CORE, "/app/.venv/bin/python", "-c", code, timeout=20)


def health(container: str) -> tuple[int, str]:
    started = time.perf_counter()
    out = sh("docker", "exec", container, "python", "-c", HEALTH_SCRIPT, timeout=8)
    return round((time.perf_counter() - started) * 1000), out.splitlines()[-1] if out else "error"


def vllm_health() -> tuple[int, str]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(VLLM_HEALTH, timeout=4) as r:
            code = str(r.status)
    except Exception:  # noqa: BLE001
        code = "error"
    return round((time.perf_counter() - started) * 1000), code


def counts() -> dict:
    kinds = psql("select kind,count(*) from knowledge_items group by 1 order by 1")
    outbox = psql("select count(*), count(*) filter (where attempts>0), count(*) filter (where failed_at is not null), count(*) filter (where locked_until is not null and locked_until>now()) from knowledge_outbox")
    o = outbox.split(",") if outbox else ["?"] * 4
    return {"items_by_kind": dict(line.split(",") for line in kinds.splitlines() if line), "items": int(psql("select count(*) from knowledge_items") or -1),
            "outbox_rows": o[0], "outbox_attempted": o[1], "outbox_failed": o[2], "outbox_leased": o[3]}


def pools() -> dict:
    line = core_python(PGB_SCRIPT).splitlines()
    parts = line[-1].split() if line else []
    keys = ("cl_active", "cl_waiting", "sv_active", "sv_idle", "maxwait")
    return dict(zip(keys, (int(float(p)) for p in parts), strict=False)) if len(parts) == 5 else {}


def host() -> dict:
    mem = next((int(line.split()[1]) // 1024 for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable")), -1)
    return {"load1": float(Path("/proc/loadavg").read_text().split()[0]), "available_mb": mem}


def container_stats() -> dict:
    out = sh("docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}|{{.MemUsage}}", CORE, timeout=15)
    cpu, _, mem = out.partition("|")
    return {"core_cpu": cpu.strip(), "core_mem": mem.split("/")[0].strip()}


def pg_connections() -> int:
    return int(psql("select count(*) from pg_stat_activity") or -1)


def preflight() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append((name, bool(ok), detail))

    add("database revision", psql("select version_num from alembic_version") == REQUIRED_REVISION, psql("select version_num from alembic_version"))
    flag = sh("docker", "exec", CORE, "printenv", "KNOWLEDGE_INDEXING_ENABLED")
    add("indexing flag is false", flag == "false", flag or "unset")
    add("shadow flag is not set", sh("docker", "exec", CORE, "printenv", "KNOWLEDGE_SHADOW_ENABLED") in ("", "false"), "must stay off for the trial")
    for name, container in (("core", CORE), ("hub", HUB)):
        ms, code = health(container)
        add(f"{name} healthy", code == "200", f"{code} in {ms} ms")
    ms, code = vllm_health()
    add("vLLM healthy", code == "200", f"{code} in {ms} ms")
    status = sh("docker", "inspect", PGB, "--format", "{{.State.Health.Status}}")
    add("PgBouncer healthy", status == "healthy", status)
    p = pools()
    add("PgBouncer idle: no waiting clients", bool(p) and p["cl_waiting"] == 0 and p["maxwait"] == 0, str(p))
    conns = pg_connections()
    add("PostgreSQL connections well below the limit", 0 < conns <= 20, f"{conns} of 100")
    h = host()
    add("host load and memory", h["load1"] < 6 and h["available_mb"] > 6000, str(h))
    due = psql("select (select count(*) from alarms where status='scheduled' and enabled and due_at between now() and now()+interval '45 minutes') + "
               "(select count(*) from reminders where status='pending' and due_at between now() and now()+interval '45 minutes')")
    add("no alarm or reminder due within 45 minutes", due == "0", f"{due} due")
    live = psql("select count(*) from meetings where status not in ('complete','failed','cancelled')")
    add("no meeting in progress or processing", live == "0", f"{live} active")
    c = counts()
    add("outbox empty and no failed rows", c["outbox_rows"] == "0" and c["outbox_failed"] == "0", str({k: c[k] for k in ("outbox_rows", "outbox_failed")}))
    add("index present (derived data only)", c["items"] >= 0, f"{c['items']} rows {c['items_by_kind']}")
    backups = sorted((Path.home() / "reachy-backups").glob("reachy-before-phase44e-indexing-trial-*.dump"))
    add("a pre-trial dump exists (take one with pg_dump per the plan)", bool(backups), backups[-1].name if backups else "none yet")
    add("model-manager reachable", sh("curl", "-s", "-m", "4", "http://172.17.0.1:8090/health").find("ok") >= 0, "no deep-review transition may be running")
    return checks


def monitor(seconds: int, log: Path, stop_file: Path) -> int:
    header = ["t", "pg_conns", "cl_active", "cl_waiting", "sv_active", "sv_idle", "maxwait", "core_ms", "hub_ms", "vllm_ms", "load1", "available_mb", "core_cpu", "core_mem",
              "items", "outbox_rows", "outbox_attempted", "outbox_failed", "outbox_leased"]
    log.write_text("\t".join(header) + "\n")
    end, waits, unhealthy, last_stats = time.monotonic() + seconds, 0, 0, {"core_cpu": "", "core_mem": ""}
    tick = 0
    while time.monotonic() < end:
        t0 = time.monotonic()
        pg, pl, c, h = pg_connections(), pools(), counts(), host()
        (cms, ccode), (hms, hcode), (vms, vcode) = health(CORE), health(HUB), vllm_health()
        if tick % 2 == 0:
            last_stats = container_stats()
        tick += 1
        row = [datetime.now(UTC).strftime("%H:%M:%S"), pg, pl.get("cl_active", ""), pl.get("cl_waiting", ""), pl.get("sv_active", ""), pl.get("sv_idle", ""), pl.get("maxwait", ""),
               f"{cms}:{ccode}", f"{hms}:{hcode}", f"{vms}:{vcode}", h["load1"], h["available_mb"], last_stats["core_cpu"], last_stats["core_mem"], c["items"], c["outbox_rows"],
               c["outbox_attempted"], c["outbox_failed"], c["outbox_leased"]]
        with log.open("a") as f:
            f.write("\t".join(str(x) for x in row) + "\n")
        waits = waits + 1 if pl.get("cl_waiting", 0) > 0 else 0
        unhealthy = unhealthy + 1 if (ccode, hcode, vcode) != ("200", "200", "200") or max(cms, hms) > GATES["health_ms"] else 0
        reason = (f"PostgreSQL connections {pg}" if pg >= GATES["pg_connections"] else
                  "PgBouncer clients waiting on consecutive samples" if waits >= GATES["waiting_samples"] else
                  f"PgBouncer maxwait {pl.get('maxwait')} s" if pl.get("maxwait", 0) >= GATES["maxwait_s"] else
                  "service health failing or slow twice running" if unhealthy >= 2 else
                  f"load {h['load1']}" if h["load1"] > GATES["load"] else
                  f"available memory {h['available_mb']} MB" if h["available_mb"] < GATES["min_available_mb"] else
                  "outbox row failed" if str(c["outbox_failed"]) not in ("0", "") else
                  "stop file" if stop_file.exists() else "")
        if reason:
            Path(str(log) + ".ABORT").write_text(reason + "\n")
            print("ABORT:", reason, file=sys.stderr)
            return 3
        time.sleep(max(0.0, 3.0 - (time.monotonic() - t0)))
    return 0


def watch(seconds: int, log: Path) -> int:
    """One long-lived psql session re-running a small read every 0.25 s: the only way to see a claim and its lease that lasts milliseconds."""
    sql = ("select to_char(clock_timestamp(),'HH24:MI:SS.MS') ts, (select count(*) from knowledge_outbox) outbox, "
           "(select string_agg(source_type||':attempts='||attempts||':leased='||(locked_until is not null and locked_until>now())::text||':failed='||(failed_at is not null)::text, ' ') from knowledge_outbox) rows, "
           "(select count(*) from knowledge_items) items, (select max(indexed_at) from knowledge_items) newest_indexed_at\\watch 0.25")
    with log.open("w") as out:
        proc = subprocess.Popen(["docker", "exec", "-i", "-e", "PGAPPNAME=ks-trial-watch", PG, "psql", "-U", "reachy", "-d", "reachy_hub", "-At", "-F", ",", "-q"], stdin=subprocess.PIPE, stdout=out, text=True)
        proc.stdin.write(sql + "\n")
        proc.stdin.flush()
        time.sleep(seconds)
        proc.terminate()
    # Ending the docker client does not end the server-side session: close the watcher's backend explicitly so no connection is left behind.
    psql("select pg_terminate_backend(pid) from pg_stat_activity where application_name='ks-trial-watch'")
    return 0


def verify() -> int:
    """Read-only drift check of the index against the authoritative stores, in a throwaway container from the production core image (writes nothing)."""
    script = Path(__file__).with_name("knowledge_index_validate.py")
    image = sh("docker", "inspect", CORE, "--format", "{{.Image}}")
    url = sh("docker", "exec", CORE, "printenv", "DATABASE_URL")
    env = {**os.environ, "DATABASE_URL": url, "DB_PREPARE_THRESHOLD": "off"}
    proc = subprocess.run(["docker", "run", "--rm", "--network", "reachy-homelab_default", "--cpus", "1", "--memory", "2g", "-e", "DATABASE_URL", "-e", "DB_PREPARE_THRESHOLD",
                           "-v", f"{script}:/v.py:ro", "-w", "/app", image, "/app/.venv/bin/python", "/v.py"], env=env, capture_output=True, text=True, check=False)
    print(proc.stdout.replace(url, "<database url>"))
    return proc.returncode


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--out")
    mon = sub.add_parser("monitor")
    mon.add_argument("--seconds", type=int, default=900)
    mon.add_argument("--log", required=True)
    mon.add_argument("--stop-file", default="/tmp/knowledge-indexing-trial.STOP")
    wat = sub.add_parser("watch")
    wat.add_argument("--seconds", type=int, default=900)
    wat.add_argument("--log", required=True)
    sub.add_parser("snapshot")
    sub.add_parser("verify")
    a = p.parse_args()
    if a.cmd == "preflight":
        checks = preflight()
        for name, ok, detail in checks:
            print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
        if a.out:
            Path(a.out).write_text(json.dumps([{"check": n, "pass": ok, "detail": d} for n, ok, d in checks], indent=1) + "\n")
        return 0 if all(ok for _, ok, _ in checks) else 1
    if a.cmd == "monitor":
        return monitor(a.seconds, Path(a.log), Path(a.stop_file))
    if a.cmd == "watch":
        return watch(a.seconds, Path(a.log))
    if a.cmd == "snapshot":
        print(json.dumps({**counts(), "pg_connections": pg_connections(), "pools": pools(), **host(), **container_stats()}))
        return 0
    return verify()


if __name__ == "__main__":
    sys.exit(main())
