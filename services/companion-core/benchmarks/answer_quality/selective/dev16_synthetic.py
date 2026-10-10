"""Synthetic fixtures for rehearsing the acceptance runner END TO END through its real command-line entry point (Phase 44, acceptance infrastructure, 2026-10-10). Nothing here touches dev16, production
inference, the frozen candidate, the formal acceptance directory or any real authorisation.

  * a DISPOSABLE git repository (real `git` commands: HEAD, clean-tree and dirty-file checks are the runner's real ones) holding placeholder role files and synthetic cases;
  * a DISPOSABLE MOCK model service on 127.0.0.1 (ephemeral port) speaking the three endpoints the real P0 adapter uses (`/health`, `/v1/models`, a streamed `/v1/chat/completions`), which can be told to fail
    after N requests or to stall on one request so a child process can be killed mid-run;
  * a synthetic preparer for the REAL `RealP0Executor` (so its health check, model check, streaming parse, row schema and `messages_sha256` run for real, with the production retrieval stack replaced);
  * a synthetic candidate arm, synthetic reviewers (labels, citation answers) and the components dictionary the real `dev16_runner.main(argv, components)` accepts.

Safety: the P0 adapter is built with `rehearsal_mock_port`, so it refuses any target other than the mock; fixtures use manifest purpose `rehearsal`, authorisations carry purpose `rehearsal`, and the runner itself refuses
a rehearsal that points at the formal acceptance directory. Scenarios: `good` (all ten PASS once reviewers label), `thin` (too few independent opportunities: INDETERMINATE), `bad` (the candidate resolves a conflict: FAIL).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import dev16_runner as r
import p0_adjudication as pa

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
SCENARIOS = {"good": {"units": 30, "supported": 45, "resolve": False, "unregistered": 8}, "thin": {"units": 10, "supported": 45, "resolve": False, "unregistered": 0}, "bad": {"units": 30, "supported": 45, "resolve": True, "unregistered": 0}}
GOOD = {"SUPPORTED": "STATES_ANSWER", "CONFLICTED": "CONFLICT_BOTH", "UNSUPPORTED": "NOT_ESTABLISHED", "NEGATIVE_UNSUPPORTED": "NOT_ESTABLISHED", "ORDER_UNSUPPORTED": "NOT_ESTABLISHED"}
WEAK = {"CONFLICTED": "CONFLICT_ONE", "UNSUPPORTED": "ASSERTS", "NEGATIVE_UNSUPPORTED": "ASSERTS", "ORDER_UNSUPPORTED": "ASSERTS"}
MANIFEST = {"E1": {"refs": ["memory:m1"], "authorized": True}, "E2": {"refs": ["memory:m2"], "authorized": True}}


def make_cases(units: int, supported: int) -> list[dict]:
    def case(cid, status, family):
        i = cid[1:]
        return {"id": cid, "family": family, "question": f"What about fact {cid}?", "access": "owner_private", "excluded_refs": [], "temporal": "current", "modality": "text",
                "atoms": [{"id": f"A{cid}", "status": status, "relation": f"rel{i}", "subject": f"Subj{i}", "pretty": f"Subj{i}", "display": [f"val{i}"], "sources": ["memory:m1"], "needs_citation": status in pa.ANSWERABLE, "severe": status == "UNSUPPORTED"}]}

    out = [case(f"S{i}", "SUPPORTED", "mixed") for i in range(supported)]
    out += [case(f"C{i}", "CONFLICTED", "conflict") for i in range(units)] + [case(f"N{i}", "NEGATIVE_UNSUPPORTED", "negative") for i in range(units)] + [case(f"O{i}", "ORDER_UNSUPPORTED", "order") for i in range(units)]
    return out + [case(f"U{i}", "UNSUPPORTED", "control") for i in range(5)]


def sh(*args, cwd):
    return subprocess.run(["git", "-c", "user.name=rehearsal", "-c", "user.email=rehearsal@invalid", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class Fixture:
    def __init__(self, base: Path, scenario: str = "good"):
        self.base, self.scenario, self.cfg = Path(base), scenario, SCENARIOS[scenario]
        self.root, self.work, self.runs = self.base / "repo", self.base / "work", self.base / "runs"
        self.cases = make_cases(self.cfg["units"], self.cfg["supported"])
        self.by = {c["id"]: c for c in self.cases}

    # --- construction -------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def build(self, p0_effective_config: dict) -> Fixture:
        for d in (self.root, self.work):
            d.mkdir(parents=True)
        files = {}
        for role in r.REQUIRED_ROLES:
            (self.root / f"{role}.txt").write_text((HERE / "dev16_criterion6_rules.json").read_text() if role == "criterion6_rules" else f"placeholder for {role}\n")  # the rules role carries the real locked rules
            files[role] = f"{role}.txt"
        (self.root / "cases.json").write_text(json.dumps({"cases": self.cases}))
        (self.root / "p0_config.json").write_text(r.canonical(p0_effective_config))
        files.update({"cases": "cases.json", "p0_config": "p0_config.json"})
        sh("init", "-q", cwd=self.root)
        sh("add", "-A", cwd=self.root)
        sh("commit", "-q", "-m", "rehearsal fixture", cwd=self.root)
        self.commit = sh("rev-parse", "HEAD", cwd=self.root)
        manifest = r.build_manifest(self.root, files, purpose=r.PURPOSE_REHEARSAL, seed=11, commit=self.commit, cases_path="cases.json")
        self.manifest_path = self.work / "manifest.json"
        self.manifest_path.write_text(r.canonical(manifest))
        self.manifest = manifest
        (self.work / "fixture.json").write_text(json.dumps({"scenario": self.scenario}))
        return self

    def authorization(self, run_id: str, **over) -> Path:
        a = {"decision": r.AUTH_DECISION, "manifest_sha256": r.manifest_sha256(self.manifest), "run_id": run_id, "authorized_by": "REHEARSAL (synthetic)", "authorized_at": NOW.isoformat(),
             "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(), "single_use": True, "p0_model_calls_authorized": True, "purpose": "rehearsal"}
        a.update(over)
        n = len(list(self.work.glob("auth-*.json"))) + 1
        p = self.work / f"auth-{n}.json"
        p.write_text(json.dumps(a))
        return p

    # --- what each side does ---------------------------------------------------------------------------------------------------------------------------------------------------------------
    def candidate_label(self, case: dict) -> str:
        st = case["atoms"][0]["status"]
        return "CONFLICT_ONE" if (self.cfg["resolve"] and st == "CONFLICTED") else GOOD[st]

    def candidate_rows(self, cases: list[dict]) -> list[dict]:
        rows = []
        for n, c in enumerate(cases):
            a = c["atoms"][0]
            cited = "E2" if (a["status"] == "SUPPORTED" and n < self.cfg["unregistered"]) else "E1"
            rows.append(pa.row_from_labels(c, f"{a['subject']} is {a['display'][0]} [{cited}].", MANIFEST, {"blanket": False, "atoms": {a["id"]: {"label": self.candidate_label(c), "cited": [cited]}}}, "deterministic"))
        return rows

    def p0_label(self, case: dict) -> str:
        st, k = case["atoms"][0]["status"], int(case["id"][1:])
        if st == "SUPPORTED":
            return "STATES_ANSWER" if k % 2 == 0 else "NOT_ESTABLISHED"
        return WEAK.get(st, GOOD[st])

    def p0_reply(self, case: dict) -> str:
        lab = self.p0_label(case)
        a = case["atoms"][0]
        return {"STATES_ANSWER": f"{a['subject']} is {a['display'][0]} [E1].", "NOT_ESTABLISHED": "I do not know.", "ASSERTS": f"{a['subject']} is probably 7.", "CONFLICT_ONE": f"{a['subject']} is {a['display'][0]} [E1]."}.get(lab, "Unclear.")

    # --- synthetic reviewers -------------------------------------------------------------------------------------------------------------------------------------------------------------
    def reviewer_labels(self, packet_dir: Path, cand_rows: list[dict], *, flip: int = 0) -> dict:
        key = json.loads((packet_dir / "SEALED" / "p0_key.json").read_text())
        by_row = {x["id"]: x for x in cand_rows}
        labels, flipped = {}, 0
        for oid, k in sorted(key.items()):
            case = self.by[k["id"]]
            a = case["atoms"][0]
            if k["arm"] == "P0":
                lab, cited = self.p0_label(case), ["E1"]
            else:
                o = by_row[k["id"]]["outcome"]["atoms"][0]
                lab = "CONFLICT_ONE" if o["resolved"] else "CONFLICT_BOTH" if o["both"] else "STATES_ANSWER" if o["stated"] else "ASSERTS" if o["leaked"] else "NOT_ESTABLISHED" if o["identified"] else "SILENT"
                cited = o["cited_ids"]
            if flip and flipped < flip and lab == "NOT_ESTABLISHED":
                lab, flipped = "SILENT", flipped + 1
            labels[oid] = {"blanket": False, "atoms": {a["id"]: {"label": lab, "cited": cited}}}
        return labels

    def c6_answers(self, packet_dir: Path, *, answer: str = "SUPPORTS") -> dict:
        text = (packet_dir / "c6_answers_TEMPLATE.json").read_text()
        tpl = json.loads(text)
        packet = (packet_dir / "c6_packet_BLINDED.md").read_text()
        out = {}
        for oid, recs in tpl.items():
            block = packet.split(f"### {oid}")[1].split("###")[0]
            claim = next(ln for ln in block.splitlines() if ln.startswith("CLAIM:"))
            subj = claim.split("'")[1].split(" is ")[0]
            out[oid] = {eid: {"answer": answer, "span": f"{subj} is " if answer == "SUPPORTS" else ""} for eid in recs}
        return out

    def review_helpers(self, cand_rows: list[dict]):
        def record_text(case_id: str, eid: str) -> str:
            a = self.by[case_id]["atoms"][0]
            return f"{a['subject']} is {a['display'][0]} (record {eid})."

        def facts(case: dict, eid: str) -> dict:
            return {"in_manifest": True, "violations": [], "excluded": False, "in_universe": True}

        return record_text, facts, (lambda case_id, eid: f"Title of {eid}")


# --- the disposable mock model service -----------------------------------------------------------------------------------------------------------------------------------------------------------

class MockService:
    """A throwaway HTTP service on 127.0.0.1. `fail_after`: drop the connection on the (N+1)th completion. `stall_on`: block the Nth completion until released (so a test can kill the client)."""

    def __init__(self, fx: Fixture, fail_after: int | None = None, stall_on: int | None = None, models: tuple[str, ...] = ("reachy-local",)):
        self.fx, self.fail_after, self.stall_on, self.models = fx, fail_after, stall_on, models
        self.requests = []
        self.release, self.stalled = threading.Event(), threading.Event()
        replies = {c["question"]: fx.p0_reply(c) for c in fx.cases}
        svc = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj, code=200):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                svc.requests.append(("GET", self.path))
                if self.path == "/health":
                    return self._json({"ok": True})
                if self.path == "/v1/models":
                    return self._json({"data": [{"id": m} for m in svc.models]})
                self._json({"error": "unknown"}, 404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/tokenize":  # the tokenizer endpoint the context builder uses: a deterministic count, no inference
                    svc.requests.append(("POST-tokenize", self.path))
                    return self._json({"count": max(1, len(str(body.get("prompt", ""))) // 4)})
                svc.requests.append(("POST", self.path, body.get("temperature"), body.get("seed"), body.get("max_tokens")))
                n = sum(1 for q in svc.requests if q[0] == "POST")
                if svc.fail_after is not None and n > svc.fail_after:
                    self.connection.close()
                    return
                if svc.stall_on == n:
                    svc.stalled.set()
                    svc.release.wait(30)
                reply = replies.get(body["messages"][-1]["content"], "Unknown.")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for piece in (reply[: len(reply) // 2], reply[len(reply) // 2:]):
                    self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': piece}}]})}\n\n".encode())
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 11, 'completion_tokens': 5}})}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


class SynthPreparer:
    """Stands in for the production retrieval stack: messages in the declared order and one authorised evidence entry."""

    async def prepare(self, name: str, case: dict):
        assert name == "b1a"
        msgs = [{"role": "system", "content": "persona"}, {"role": "system", "content": "44H boundary"}, {"role": "system", "content": "date"}, {"role": "user", "content": case["question"]}]
        return SimpleNamespace(messages=msgs, evidence={"E1": SimpleNamespace(refs=["memory:m1"], authorized=True)})


def local_client(port: int):
    from aq import llm

    old = llm.BASE
    llm.BASE = f"http://127.0.0.1:{port}"
    try:
        return llm.Local()
    finally:
        llm.BASE = old


def components(fx: Fixture, port: int) -> dict:
    import dev16_p0 as p0

    executor = p0.RealP0Executor(fx.root / "corpus.json", llm_factory=lambda: local_client(port), preparer_factory=lambda llm: SynthPreparer(), rehearsal_mock_port=port)
    return {"p0_executor": executor, "candidate_arm": fx.candidate_rows, "candidate_check": list, "config_checks": list, "review_helpers": fx.review_helpers}


def new_fixture(base: Path, scenario: str = "good") -> Fixture:
    import dev16_p0 as p0

    return Fixture(base, scenario).build(json.loads(json.dumps(p0.effective())))


def run_cli(fx: Fixture, port: int, argv: list[str], *, approval: Path | None = None) -> int:
    """Drive the REAL entry point `dev16_runner.main` with synthetic components. The approval variable is set and restored around the call."""
    old = os.environ.get(r.APPROVAL_ENV)
    if approval is not None:
        os.environ[r.APPROVAL_ENV] = str(approval)
    else:
        os.environ.pop(r.APPROVAL_ENV, None)
    try:
        return r.main(argv, components=components(fx, port))
    finally:
        if old is None:
            os.environ.pop(r.APPROVAL_ENV, None)
        else:
            os.environ[r.APPROVAL_ENV] = old


def common(fx: Fixture) -> list[str]:
    return ["--manifest", str(fx.manifest_path), "--root", str(fx.root)]


def child_main(base: str, port: str, run_id: str, approval: str) -> int:
    """Entry point of a CHILD process that runs the CLI `run` against the mock service; a parent may kill it mid-run to test interrupted-run handling."""
    fx = Fixture(Path(base), json.loads((Path(base) / "work" / "fixture.json").read_text())["scenario"])
    fx.commit = json.loads((fx.work / "manifest.json").read_text())["commit"]
    fx.manifest_path = fx.work / "manifest.json"
    fx.manifest = json.loads(fx.manifest_path.read_text())
    return run_cli(fx, int(port), ["run", *common(fx), "--runs-root", str(fx.runs), "--run-id", run_id, "--execute"], approval=Path(approval))


if __name__ == "__main__" and len(sys.argv) == 6 and sys.argv[1] == "child":
    sys.exit(child_main(*sys.argv[2:]))
