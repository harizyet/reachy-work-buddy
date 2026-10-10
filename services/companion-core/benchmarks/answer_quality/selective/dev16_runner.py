"""Guarded, one-shot acceptance runner (Phase 44, acceptance infrastructure, 2026-10-10). INFRASTRUCTURE ONLY: written and tested on synthetic fixtures and already-consumed development data. Nothing here has
been pointed at dev16, and no P0 model call has been made. It does not change the frozen candidate, the evaluator or any scorer.

WHAT IT ENFORCES (every check fails closed: any doubt refuses, and a refusal writes nothing into a run directory):
  1  every file in the acceptance MANIFEST exists and hashes to the recorded value (candidate manifest, evaluator, aq/scoring.py, corpus, cases, P0 and candidate configurations, criterion-6 rules, runner and
     tooling); the frozen candidate itself is re-checked by its own manifest; the working tree has no changes to listed files and HEAD is the recorded commit
  2  the case population is exactly the manifest's (the cases file hash and the hash of the ordered case ids); paired case identities are the cases' ids, in file order
  3  the P0 and candidate configurations declared in the manifest equal the ones the code computes; a P0 executor is present and reports the declared configuration (a missing baseline refuses)
  4  an explicit, single-use EXECUTION AUTHORISATION bound to this manifest hash and run id, named by the environment variable AQ_DEV16_APPROVAL, not expired, never used before; plus the explicit --execute flag
  5  one shot: an exclusive lock directory per manifest hash plus an append-only ledger. Any earlier attempt for the same manifest (complete, failed, aborted or interrupted) refuses a new one; there is no
     resume and no rerun without a new manifest, which needs an owner decision
  6  immutable artifacts: files are created exclusively and never overwritten, flushed to disk as written, made read-only at the end, listed in ARTIFACTS.sha256, with provenance (commit, manifest, hashes,
     configurations, authorisation hash, environment) written before the first reply; a failure writes failure.json with the traceback and aborts the whole run (STATE.json says ABORTED); a hash check after the
     run flags COMPLETE_BUT_INVALID if anything listed changed during it

POST-RUN (no model): `build_review_packets` makes the blinded P0 semantic-adjudication packet and the criterion-6 citation packet; `evaluate_run` turns completed labels into PASS / FAIL / INDETERMINATE per
criterion (dev16_criteria.py) and never overwrites a report.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

REQUIRED_ROLES = ("candidate_manifest", "evaluator", "scoring", "corpus", "cases", "p0_config", "candidate_config", "criterion6_rules", "runner", "p0_module", "candidate_arm", "criteria_module",
                  "criterion6_module", "p0_adjudication", "deterministic_criteria", "i2b_eval")
APPROVAL_ENV = "AQ_DEV16_APPROVAL"
PURPOSE_ACCEPTANCE, PURPOSE_REHEARSAL = "dev16-acceptance", "rehearsal"
FORMAL_RUNS_DIR = HERE / "dev16_acceptance_runs"  # the ONLY place a formal acceptance may write; a rehearsal can never write here, and an acceptance can never write anywhere else
AUTH_DECISION = "AUTHORIZE_ACCEPTANCE_EXECUTION"
TERMINAL = {"COMPLETE", "COMPLETE_BUT_INVALID", "ABORTED"}


class RunRefused(RuntimeError):
    """A guard failed before anything was written into a run directory."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class RunAborted(RuntimeError):
    """The run started and was aborted; the run directory holds the failure log and what was produced."""


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def canonical(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True) + "\n"


def write_once(path: Path, data: str | bytes) -> None:
    """Create a file that must not exist, write it, flush it to disk. Never overwrites."""
    b = data.encode() if isinstance(data, str) else data
    with open(path, "xb") as f:
        f.write(b)
        f.flush()
        os.fsync(f.fileno())


def append_line(path: Path, line: str) -> None:
    with open(path, "ab") as f:
        f.write(line.encode() + b"\n")
        f.flush()
        os.fsync(f.fileno())


def case_ids_sha256(cases: list[dict]) -> str:
    return sha256_text("\n".join(c["id"] for c in cases))


def freeze_readonly(root: Path) -> None:
    for p in sorted(root.rglob("*")):
        if p.is_file():
            p.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    for p in sorted([d for d in root.rglob("*") if d.is_dir()], reverse=True) + [root]:
        p.chmod(stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)


# --- manifest ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def build_manifest(root: Path, files: dict[str, str], *, purpose: str, seed: int, commit: str, cases_path: str | None = None) -> dict:
    """Hash every listed file (paths relative to `root`) into a manifest. At the dev16 freeze `cases_path` is hashed and parsed for its ids; until then nothing here is pointed at dev16."""
    m = {"purpose": purpose, "created_at": datetime.now(UTC).isoformat(), "commit": commit, "seed": seed, "files": {role: {"path": rel, "sha256": sha256_file(root / rel)} for role, rel in sorted(files.items())}}
    if cases_path:
        cases = json.loads((root / cases_path).read_text())["cases"]
        m["case_count"], m["case_ids_sha256"] = len(cases), case_ids_sha256(cases)
    return m


def manifest_sha256(manifest: dict) -> str:
    return sha256_text(canonical(manifest))


def verify_manifest(manifest: dict, root: Path) -> list[str]:
    problems = []
    files = manifest.get("files", {})
    for role in REQUIRED_ROLES:
        if role not in files:
            problems.append(f"manifest lacks the required role {role!r}")
    for role, ent in files.items():
        p = root / ent["path"]
        if not p.is_file():
            problems.append(f"{role}: file missing: {ent['path']}")
        elif sha256_file(p) != ent["sha256"]:
            problems.append(f"{role}: hash mismatch: {ent['path']}")
    for key in ("purpose", "commit", "seed", "case_count", "case_ids_sha256"):
        if key not in manifest:
            problems.append(f"manifest lacks {key!r}")
    return problems


def git_info(root: Path) -> dict:
    def run(*a):
        return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=True).stdout

    # porcelain lines are " M path" / "M  path" / "?? path": the two status columns are positional, so the output must NOT be stripped (stripping once cut the first path's first character)
    dirty = [ln[3:].strip() for ln in run("status", "--porcelain", "--untracked-files=no").splitlines() if ln.strip()]
    return {"head": run("rev-parse", "HEAD").strip(), "dirty_tracked": dirty}


# --- authorisation, locks, ledger ------------------------------------------------------------------------------------------------------------------------------------------------------------

def check_authorization(path: Path | None, manifest_sha: str, run_id: str, now: datetime, ledger: Path, purpose: str | None = None) -> tuple[list[str], str | None]:
    if path is None or not Path(path).is_file():
        return ["no execution authorisation file (set AQ_DEV16_APPROVAL to its path)"], None
    raw = Path(path).read_bytes()
    try:
        a = json.loads(raw)
    except ValueError:
        return ["the authorisation file is not valid JSON"], None
    sha = hashlib.sha256(raw).hexdigest()
    problems = []
    if a.get("decision") != AUTH_DECISION:
        problems.append("the authorisation does not carry the execution decision")
    if a.get("manifest_sha256") != manifest_sha:
        problems.append("the authorisation is bound to a different manifest")
    if purpose is not None and a.get("purpose") != purpose:
        problems.append(f"the authorisation is for the purpose {a.get('purpose')!r}, not {purpose!r}: a rehearsal and a formal acceptance can never use each other's authorisation")
    if a.get("run_id") != run_id:
        problems.append("the authorisation is bound to a different run id")
    if not a.get("authorized_by"):
        problems.append("the authorisation names no authoriser")
    if a.get("single_use") is not True or a.get("p0_model_calls_authorized") is not True:
        problems.append("the authorisation must set single_use and p0_model_calls_authorized")
    try:
        if datetime.fromisoformat(a.get("expires_at", "")) < now:
            problems.append("the authorisation has expired")
    except ValueError:
        problems.append("the authorisation has no valid expires_at")
    if ledger.exists() and any(json.loads(ln).get("authorization_sha256") == sha for ln in ledger.read_text().splitlines() if ln.strip()):
        problems.append("this authorisation was already used")
    return problems, sha


def ledger_entries(ledger: Path) -> list[dict]:
    return [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()] if ledger.exists() else []


def inspect_runs(runs_root: Path, manifest_sha: str) -> dict:
    """What earlier attempts exist for this manifest and in which state."""
    out = {"lock": (runs_root / f"LOCK-{manifest_sha[:16]}").exists(), "runs": []}
    for d in sorted(runs_root.glob("run-*")) if runs_root.exists() else []:
        st = d / "STATE.json"
        state = json.loads(st.read_text()) if st.exists() else {"state": "NO_STATE"}
        if state.get("manifest_sha256") == manifest_sha:
            out["runs"].append({"dir": d.name, "state": state["state"], "terminal": state["state"] in TERMINAL})
    return out


# --- the run -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def preflight(manifest_path: Path, root: Path, runs_root: Path, run_id: str, *, p0_executor, candidate_arm: Callable, authorization_path: Path | None, execute_flag: bool, now: datetime | None = None,
              git: Callable[[Path], dict] = git_info, candidate_check: Callable[[], list[str]] | None = None, config_checks: Callable[[], list[str]] | None = None, dry: bool = False) -> dict:
    """Every guard, in order. `dry` skips the execution flag and authorisation (to check readiness) and logs nothing. Returns the facts the run needs; raises RunRefused listing EVERY problem found (a refusal creates no run directory)."""
    now = now or datetime.now(UTC)
    problems: list[str] = []
    try:
        manifest = json.loads(Path(manifest_path).read_text())
    except (OSError, ValueError) as exc:
        raise RunRefused([f"the manifest cannot be read: {exc}"]) from exc
    msha = manifest_sha256(manifest)
    problems += verify_manifest(manifest, root)
    if candidate_check is not None:
        problems += [f"frozen candidate: {p}" for p in candidate_check()]
    if config_checks is not None:
        problems += config_checks()
    try:
        g = git(root)
    except Exception as exc:  # noqa: BLE001  (any failure to read the repository state refuses)
        g = {"head": "", "dirty_tracked": []}
        problems.append(f"the repository state cannot be read: {type(exc).__name__}")
    if g["head"] != manifest.get("commit"):
        problems.append(f"HEAD {g['head'][:12]} is not the manifest commit {str(manifest.get('commit'))[:12]}")
    listed = {e["path"] for e in manifest.get("files", {}).values()}
    problems += [f"tracked file changed in the working tree: {p}" for p in g["dirty_tracked"] if p in listed]
    cases = []
    cases_file = root / manifest.get("files", {}).get("cases", {}).get("path", "")
    if cases_file.is_file():
        try:
            cases = json.loads(cases_file.read_text())["cases"]
            if len(cases) != manifest.get("case_count") or case_ids_sha256(cases) != manifest.get("case_ids_sha256"):
                problems.append("the case population differs from the manifest (count or ordered ids)")
            if len({c["id"] for c in cases}) != len(cases):
                problems.append("duplicate case ids")
        except (ValueError, KeyError, TypeError):
            cases = []
            problems.append("the cases file cannot be read as a list of cases")
    if p0_executor is None:
        problems.append("no P0 baseline executor: a missing baseline refuses the run")
    elif sha256_text(canonical(p0_executor.effective_config())) != manifest.get("files", {}).get("p0_config", {}).get("sha256"):
        problems.append("the P0 executor's effective configuration differs from the declared (manifest-hashed) one")
    if candidate_arm is None:
        problems.append("no candidate arm")
    if not execute_flag and not dry:
        problems.append("--execute was not given")
    purpose = manifest.get("purpose")
    rr, formal = Path(runs_root).resolve(), FORMAL_RUNS_DIR.resolve()
    in_formal = rr == formal or formal in rr.parents
    if purpose not in (PURPOSE_ACCEPTANCE, PURPOSE_REHEARSAL):
        problems.append(f"the manifest purpose {purpose!r} is neither {PURPOSE_ACCEPTANCE!r} nor {PURPOSE_REHEARSAL!r}")
    elif purpose == PURPOSE_REHEARSAL and in_formal:
        problems.append("a rehearsal may never write to the formal acceptance output directory")
    elif purpose == PURPOSE_ACCEPTANCE and rr != formal:
        problems.append(f"a formal acceptance must write to {formal}, not {rr}")
    if (runs_root / f"LOCK-{msha[:16]}").exists():
        problems.append("a run for this manifest already exists (complete, failed, aborted or interrupted): one shot only")
    if (runs_root / run_id).exists():
        problems.append("the run directory already exists")
    if any(e.get("manifest_sha256") == msha for e in ledger_entries(runs_root / "LEDGER.jsonl")):
        problems.append("the ledger already records an attempt for this manifest")
    auth_sha = None
    if not dry:
        auth_problems, auth_sha = check_authorization(authorization_path, msha, run_id, now, runs_root / "LEDGER.jsonl", purpose)
        problems += auth_problems
    if problems and dry:
        raise RunRefused(problems)
    if problems:
        if purpose == PURPOSE_REHEARSAL and in_formal:
            raise RunRefused(problems)  # nothing is written into the formal directory, not even a refusal note
        runs_root.mkdir(parents=True, exist_ok=True)
        append_line(runs_root / "REFUSALS.jsonl", json.dumps({"at": now.isoformat(), "run_id": run_id, "manifest_sha256": msha, "problems": problems}))
        raise RunRefused(problems)
    return {"manifest": manifest, "manifest_sha256": msha, "cases": cases, "git": g, "authorization_sha256": auth_sha}


def set_state(run_dir: Path, **fields) -> None:
    tmp = run_dir / "STATE.json.tmp"
    if tmp.exists():
        tmp.unlink()
    write_once(tmp, canonical({**fields, "updated_at": datetime.now(UTC).isoformat()}))
    os.replace(tmp, run_dir / "STATE.json")


def execute(manifest_path: Path, root: Path, runs_root: Path, run_id: str, *, p0_executor, candidate_arm: Callable[[list[dict]], list[dict]], authorization_path: Path | None, execute_flag: bool,
            now: datetime | None = None, git: Callable[[Path], dict] = git_info, candidate_check: Callable[[], list[str]] | None = None, config_checks: Callable[[], list[str]] | None = None) -> Path:
    """One shot. Returns the run directory. Raises RunRefused (nothing written into a run) or RunAborted (the run directory holds the failure log)."""
    facts = preflight(manifest_path, root, runs_root, run_id, p0_executor=p0_executor, candidate_arm=candidate_arm, authorization_path=authorization_path, execute_flag=execute_flag, now=now, git=git,
                      candidate_check=candidate_check, config_checks=config_checks)
    manifest, msha, cases = facts["manifest"], facts["manifest_sha256"], facts["cases"]
    runs_root.mkdir(parents=True, exist_ok=True)
    os.mkdir(runs_root / f"LOCK-{msha[:16]}")  # exclusive: the one-shot guard (raises FileExistsError if another process won the race)
    run_dir = runs_root / run_id
    os.mkdir(run_dir)
    append_line(runs_root / "LEDGER.jsonl", json.dumps({"event": "START", "run_id": run_id, "manifest_sha256": msha, "authorization_sha256": facts["authorization_sha256"], "at": datetime.now(UTC).isoformat()}))
    state = {"run_id": run_id, "manifest_sha256": msha}
    try:
        files = {role: {**e, "verified": True} for role, e in manifest["files"].items()}
        write_once(run_dir / "provenance.json", canonical({"run_id": run_id, "mode": manifest["purpose"], "started_at": datetime.now(UTC).isoformat(), "manifest_sha256": msha, "manifest": manifest, "files": files,
                                                           "git": facts["git"], "authorization_sha256": facts["authorization_sha256"], "p0_effective_config": p0_executor.effective_config(),
                                                           "python": sys.version, "platform": platform.platform(), "argv": sys.argv, "env": {k: os.environ[k] for k in sorted(os.environ) if k.startswith("AQ_")}}))
        write_once(run_dir / "manifest.json", canonical(manifest))
        set_state(run_dir, state="STARTED", **state)
        cand = candidate_arm(cases)
        if [r["id"] for r in cand] != [c["id"] for c in cases]:
            raise RuntimeError("candidate rows do not cover the frozen cases in order")
        write_once(run_dir / "candidate_rows.jsonl", "\n".join(json.dumps(r, sort_keys=True, default=str) for r in cand) + "\n")
        set_state(run_dir, state="CANDIDATE_DONE", **state)
        p0_executor.open()
        environment = getattr(p0_executor, "environment", None)
        if environment:  # what the P0 environment actually was: database image and versions, embedding identity, offline flags, the served-model response
            write_once(run_dir / "p0_environment.json", canonical(environment))
        set_state(run_dir, state="P0_RUNNING", completed=0, **state)
        out = run_dir / "p0_rows.jsonl"
        n = 0
        try:
            for c in cases:
                row = p0_executor.run_case(c)
                if row.get("id") != c["id"] or not isinstance(row.get("reply"), str) or not isinstance(row.get("manifest"), dict):
                    raise RuntimeError(f"malformed P0 row for {c['id']}")
                append_line(out, json.dumps(row, sort_keys=True))
                n += 1
                set_state(run_dir, state="P0_RUNNING", completed=n, **state)
        finally:
            p0_executor.close()
        if n != len(cases):
            raise RuntimeError("the P0 arm did not cover every case")
        set_state(run_dir, state="P0_DONE", **state)
        invalid = verify_manifest(manifest, root)
        final = "COMPLETE" if not invalid else "COMPLETE_BUT_INVALID"
        write_once(run_dir / "post_run_check.json", canonical({"problems": invalid, "checked_at": datetime.now(UTC).isoformat()}))
        write_once(run_dir / "ARTIFACTS.sha256", "".join(f"{sha256_file(p)}  {p.name}\n" for p in sorted(run_dir.iterdir()) if p.is_file() and p.name not in ("STATE.json", "ARTIFACTS.sha256")))
        set_state(run_dir, state=final, completed=n, **state)
        append_line(runs_root / "LEDGER.jsonl", json.dumps({"event": final, "run_id": run_id, "manifest_sha256": msha, "authorization_sha256": facts["authorization_sha256"], "at": datetime.now(UTC).isoformat()}))
        freeze_readonly(run_dir)
        return run_dir
    except BaseException as exc:
        try:
            write_once(run_dir / "failure.json", canonical({"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(), "at": datetime.now(UTC).isoformat(), "rule": "a failed run is not repeated or resumed without an owner decision"}))
            set_state(run_dir, state="ABORTED", error=f"{type(exc).__name__}: {exc}", **state)
            append_line(runs_root / "LEDGER.jsonl", json.dumps({"event": "ABORTED", "run_id": run_id, "manifest_sha256": msha, "authorization_sha256": facts["authorization_sha256"], "error": f"{type(exc).__name__}: {exc}", "at": datetime.now(UTC).isoformat()}))
            freeze_readonly(run_dir)
        finally:
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
        raise RunAborted(f"{type(exc).__name__}: {exc}") from exc


# --- post-run: blinded packets and evaluation -------------------------------------------------------------------------------------------------------------------------------------------

def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(ln) for ln in Path(p).read_text().splitlines() if ln.strip()]


def require_complete(run_dir: Path) -> dict:
    st = json.loads((run_dir / "STATE.json").read_text())
    if st["state"] != "COMPLETE":
        raise RunRefused([f"the run is {st['state']}, not COMPLETE: its results are not usable for acceptance"])
    for line in (run_dir / "ARTIFACTS.sha256").read_text().splitlines():
        h, name = line.split(None, 1)
        if sha256_file(run_dir / name.strip()) != h:
            raise RunRefused([f"run artifact changed after the run: {name.strip()}"])
    return st


def build_review_packets(run_dir: Path, cases: dict, record_text: Callable[[str, str], str], facts: Callable[[dict, str], dict], *, seed: int, rules_sha256: str,
                         record_context: Callable[[str, str], str] | None = None) -> dict:
    """Blinded packets into <run>/review/ (exclusive creation). Needs only the completed run, the cases, record texts and code facts. No model."""
    import dev16_criterion6 as c6
    import p0_adjudication as pa

    require_complete(run_dir)
    rules = c6.load_rules(rules_sha256)
    review = run_dir.parent / f"{run_dir.name}-review"
    os.mkdir(review)
    cand, p0 = read_jsonl(run_dir / "candidate_rows.jsonl"), read_jsonl(run_dir / "p0_rows.jsonl")
    items, key = pa.build_packet(p0, cand, cases, seed=seed)
    write_once(review / "p0_packet_BLINDED.md", pa.render_packet(items))
    write_once(review / "p0_labels_TEMPLATE.json", canonical(pa.template(items)))
    claims = c6.cited_claims(cand, cases)
    selected = c6.select_for_review(claims, record_text, seed=seed)
    c6items, c6key = c6.build_packet(selected, cases, record_text, facts, seed=seed, record_context=record_context)
    write_once(review / "c6_packet_BLINDED.md", c6.render_packet(c6items, rules))
    write_once(review / "c6_answers_TEMPLATE.json", canonical(c6.template(c6items)))
    sealed = review / "SEALED"
    os.mkdir(sealed)
    write_once(sealed / "p0_key.json", canonical(key))
    write_once(sealed / "c6_key.json", canonical({"key": c6key, "selected": [{k: v for k, v in c.items()} for c in selected]}))
    sizes = {"p0_replies": len(items), "p0_parts": sum(len(i["atoms"]) for i in items), "p0_control_replies": sum(k["arm"] == "candidate" for k in key.values()), "c6_claims_reviewed": len(c6items),
             "c6_cited_claims_total": len(claims), "c6_mechanically_unsupported": sum(not c["mechanical"] for c in claims), "c6_controls": sum(c["why"] == "control" for c in selected)}
    write_once(review / "SIZES.json", canonical(sizes))
    write_once(review / "MANIFEST.sha256", "".join(f"{sha256_file(p)}  {p.relative_to(review)}\n" for p in sorted(review.rglob("*")) if p.is_file() and p.name != "MANIFEST.sha256"))
    return sizes


def evaluate_run(run_dir: Path, cases: dict, record_text: Callable[[str, str], str], facts: Callable[[dict, str], dict], *, seed: int, rules_sha256: str, labels_a: dict | None, labels_b: dict | None,
                 c6_a: dict | None, c6_b: dict | None, labels_reconciled: dict | None = None, record_context: Callable[[str, str], str] | None = None) -> dict:
    """Turn completed labels into the per-criterion report. Writes <run>-report/ exclusively; never overwrites. FIRST the independent label files (A, B, citation answers) are copied into the report directory
    and hashed, BEFORE any agreement is computed or any reconciliation is read, so independence of the labels is preserved on record. Reconciled labels, if given, are a separate variant that must cite those hashes.
    Labels left incomplete make the baseline-relative criteria INDETERMINATE."""
    import dev16_criteria as crit
    import dev16_criterion6 as c6
    import evaluator
    import p0_adjudication as pa

    require_complete(run_dir)
    rules = c6.load_rules(rules_sha256)
    out = run_dir.parent / f"{run_dir.name}-report"
    os.mkdir(out)
    ind = out / "independent_labels"
    os.mkdir(ind)
    hashes = {}
    for name, obj in (("p0_labels_A", labels_a), ("p0_labels_B", labels_b), ("c6_answers_A", c6_a), ("c6_answers_B", c6_b)):
        if obj is not None:
            write_once(ind / f"{name}.json", canonical(obj))
            hashes[name] = sha256_file(ind / f"{name}.json")
    for p in ind.iterdir():
        p.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    write_once(out / "independent_labels.sha256", "".join(f"{h}  {n}.json\n" for n, h in sorted(hashes.items())))
    cand, p0 = read_jsonl(run_dir / "candidate_rows.jsonl"), read_jsonl(run_dir / "p0_rows.jsonl")
    key = json.loads((run_dir.parent / f"{run_dir.name}-review" / "SEALED" / "p0_key.json").read_text())
    oid_of = {(k["arm"], k["id"]): o for o, k in key.items()}
    items, _ = pa.build_packet(p0, cand, cases, seed=seed)

    def rows_from(labels):
        if not labels or pa.complete(labels, items):
            return None
        return [pa.row_from_labels(cases[r["id"]], r["reply"], r["manifest"], labels[oid_of[("P0", r["id"])]], "P0") for r in p0]

    rows_a, rows_b, rows_r = rows_from(labels_a), rows_from(labels_b), rows_from(labels_reconciled)
    agreement = pa.agreement(labels_a, labels_b) if rows_a is not None and rows_b is not None else None
    selected = c6.select_for_review(c6.cited_claims(cand, cases), record_text, seed=seed)
    adjud = c6.adjudicate(selected, {}, cases, c6_a, c6_b, record_text, facts, seed=seed, record_context=record_context)
    c6s = c6.summarize(evaluator.metrics(cand, cases), adjud, rules)
    report = {"run": run_dir.name, "independent_label_hashes": hashes, "identical_label_files_warning": bool(labels_a is not None and labels_a == labels_b), "variants": {}}
    for name, rows in (("reviewer_A", rows_a), ("reviewer_B", rows_b)):
        report["variants"][name] = crit.assess(cand, rows, cases, c6s, agreement=agreement) if (rows is not None or name == "reviewer_A") else None
    if labels_reconciled is not None:
        report["variants"]["reconciled"] = crit.assess(cand, rows_r, cases, c6s, agreement=agreement) if rows_r is not None else None
        report["reconciled_labels_sha256"] = sha256_text(canonical(labels_reconciled))
    report["agreement"] = agreement and {k: v for k, v in agreement.items() if k != "disagreements"}
    report["disagreements"] = agreement["disagreements"] if agreement else []
    report["criterion6"] = c6s
    report["criterion6_adjudication"] = adjud
    write_once(out / "report.json", canonical(report))
    return report


def real_components(root: Path, manifest: dict) -> dict:
    """The production components: the frozen candidate arm with per-case authorisation, the real P0 executor, the real candidate-freeze and configuration checks, review helpers over the frozen World."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import candidate_freeze
    import dev16_candidate_arm as ca
    import dev16_p0 as p0
    import i2b_eval as e

    corpus = root / manifest["files"]["corpus"]["path"]

    def arm(cases):
        world, meta, profiles = ca.load_world(corpus)
        return ca.candidate_rows(world, cases, e.make_planners(world, cases)["T-new"], meta, profiles)

    def helpers(cand_rows):
        world, meta, profiles = ca.load_world(corpus)
        return ca.review_helpers(world, meta, profiles, cand_rows)

    return {"p0_executor": p0.RealP0Executor(corpus), "candidate_arm": arm, "candidate_check": candidate_freeze.check, "config_checks": lambda: p0.verify_declared() + ca.verify_declared(), "review_helpers": helpers}


def main(argv: list[str], components: dict | None = None) -> int:
    """Command line. `run` is the only command that can call the model, and only after every guard, with --execute, and with AQ_DEV16_APPROVAL naming a single-use authorisation of the right purpose.
    `components` lets a rehearsal drive THIS entry point with synthetic parts (a mock P0 service, a synthetic candidate arm); without it the production components are used. The real P0 adapter has
    been exercised only against a disposable mock service, never against production inference."""
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("inspect", help="show the state of earlier attempts for a manifest")
    s.add_argument("--manifest", required=True)
    s.add_argument("--runs-root", required=True)
    for name in ("verify", "run"):
        s = sub.add_parser(name, help="run every guard without executing (verify) or execute once (run)")
        for a in ("--manifest", "--root", "--runs-root", "--run-id"):
            s.add_argument(a, required=True)
        if name == "run":
            s.add_argument("--execute", action="store_true")
    for name in ("packets", "evaluate"):
        s = sub.add_parser(name, help="post-run, no model")
        for a in ("--manifest", "--root", "--run-dir"):
            s.add_argument(a, required=True)
        if name == "evaluate":
            for a in ("--p0-labels-a", "--p0-labels-b", "--p0-labels-reconciled", "--c6-answers-a", "--c6-answers-b"):
                s.add_argument(a)
    args = ap.parse_args(argv)
    if args.cmd == "inspect":
        m = json.loads(Path(args.manifest).read_text())
        print(json.dumps(inspect_runs(Path(args.runs_root), manifest_sha256(m)), indent=1))
        return 0
    try:
        manifest = json.loads(Path(args.manifest).read_text())
    except (OSError, ValueError) as exc:
        print(f"REFUSED: the manifest cannot be read: {exc}")
        return 1
    root = Path(args.root)
    comp = components if components is not None else real_components(root, manifest)
    checks = {"candidate_check": comp["candidate_check"], "config_checks": comp["config_checks"]}

    if args.cmd in ("verify", "run"):
        approval = os.environ.get(APPROVAL_ENV)
        try:
            if args.cmd == "verify":
                preflight(Path(args.manifest), root, Path(args.runs_root), args.run_id, p0_executor=comp["p0_executor"], candidate_arm=comp["candidate_arm"], authorization_path=None, execute_flag=False, dry=True, **checks)
                print("all guards pass (nothing executed)")
                return 0
            d = execute(Path(args.manifest), root, Path(args.runs_root), args.run_id, p0_executor=comp["p0_executor"], candidate_arm=comp["candidate_arm"], authorization_path=Path(approval) if approval else None,
                        execute_flag=args.execute, **checks)
            print(f"run complete: {d}")
            return 0
        except RunRefused as exc:
            print("REFUSED:\n- " + "\n- ".join(exc.problems))
            return 1
        except RunAborted as exc:
            print(f"ABORTED: {exc}; see the run directory's failure.json. No rerun without an owner decision.")
            return 3

    import dev16_criterion6 as c6

    cases_list = json.loads((root / manifest["files"]["cases"]["path"]).read_text())["cases"]
    by = {c["id"]: c for c in cases_list}
    run_dir = Path(args.run_dir)
    cand = read_jsonl(run_dir / "candidate_rows.jsonl")
    helpers = comp["review_helpers"](cand)
    record_text, facts = helpers[0], helpers[1]
    record_context = helpers[2] if len(helpers) > 2 else None
    rules_sha = manifest["files"]["criterion6_rules"]["sha256"]
    try:
        if args.cmd == "packets":
            print(json.dumps(build_review_packets(run_dir, by, record_text, facts, seed=manifest["seed"], rules_sha256=rules_sha, record_context=record_context), indent=1))
        else:
            load = (lambda p: json.loads(Path(p).read_text()) if p else None)
            rep = evaluate_run(run_dir, by, record_text, facts, seed=manifest["seed"], rules_sha256=rules_sha, labels_a=load(args.p0_labels_a), labels_b=load(args.p0_labels_b), c6_a=load(args.c6_answers_a),
                               c6_b=load(args.c6_answers_b), labels_reconciled=load(args.p0_labels_reconciled), record_context=record_context)
            print(json.dumps({k: (v["overall"], v["counts"]) if v else None for k, v in rep["variants"].items()}, indent=1))
        return 0
    except (RunRefused, c6.RulesError, FileExistsError) as exc:
        print(f"REFUSED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
