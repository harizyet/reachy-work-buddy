"""Phase 44 P0 reproducibility correction (R1 provenance, R2 offline assets, R3 deterministic retrieval). Consumed dev15 data and the invented corpus only; no model call. The database-backed tests run only when a
DISPOSABLE PostgreSQL with pgvector is named in KBENCH_DATABASE_URL (they skip otherwise); the embedding tests skip when the model is not cached."""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

SEL = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality" / "selective"
KB = SEL.parents[1] / "knowledge_retrieval"


def _load(name, path=None):
    saved = list(sys.argv)
    sys.path[:0] = [str(SEL), str(SEL.parent), str(KB)]
    try:
        spec = importlib.util.spec_from_file_location(name, path or SEL / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.argv[:] = saved
        del sys.path[:3]


P0 = _load("dev16_p0")
RUN = _load("dev16_runner")
PGENV = _load("pg_env_under_test", KB / "kbench" / "pg_env.py")
DIGEST = "sha256:" + "a" * 64


# -- R3: stable ids ------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_stable_ids_are_a_function_of_the_logical_key_and_the_call_index_and_are_restored():
    real = uuid.uuid4
    with PGENV.stable_ids("memory:m001"):
        a = [uuid.uuid4() for _ in range(3)]
    with PGENV.stable_ids("memory:m001"):
        b = [uuid.uuid4() for _ in range(3)]
    with PGENV.stable_ids("memory:m002"):
        c = uuid.uuid4()
    assert a == b and len(set(a)) == 3 and c not in a and all(x.version == 5 for x in a)
    assert a[0] == uuid.uuid5(PGENV.STABLE_ID_NAMESPACE, "memory:m001#0")
    assert uuid.uuid4 is real and uuid.uuid4() != uuid.uuid4()  # random again afterwards


def test_stable_ids_disabled_changes_nothing_and_an_exception_still_restores_the_generator():
    real = uuid.uuid4
    with PGENV.stable_ids("x", enabled=False):
        assert uuid.uuid4 is real
    with pytest.raises(RuntimeError), PGENV.stable_ids("x"):
        raise RuntimeError("boom")
    assert uuid.uuid4 is real


def test_the_database_name_is_still_random_because_it_uses_the_name_imported_at_load():
    assert PGENV.uuid4 is not uuid.uuid5 and "uuid4" in (KB / "kbench" / "pg_env.py").read_text()
    with PGENV.stable_ids("k"):
        assert PGENV.uuid4().hex != PGENV.uuid4().hex  # the module-level reference is unpatched


# -- R1: pinned sources and the environment record -----------------------------------------------------------------------------------------------------------------------------------------

def test_the_build_helper_and_the_embedding_module_are_pinned_in_the_p0_declaration():
    declared = json.loads(P0.CONFIG_PATH.read_text())
    assert "../knowledge_retrieval/kbench/pg_env.py" in declared["computed"]["source_sha256"] and "../../src/companion_core/rag/embeddings.py" in declared["computed"]["source_sha256"]
    assert "STABLE" in declared["environment"]["record_ids"] and "HF_HUB_OFFLINE=1" in declared["environment"]["offline"] and "/v1/models" in declared["environment"]["served_model"]


def test_the_database_image_must_be_declared_and_well_formed():
    for bad in ({}, {"AQ_PG_IMAGE_DIGEST": ""}, {"AQ_PG_IMAGE_DIGEST": "latest"}, {"AQ_PG_IMAGE_DIGEST": "sha256:abc"}):
        with pytest.raises(RuntimeError, match="AQ_PG_IMAGE_DIGEST"):
            P0.database_image(bad)
    assert P0.database_image({"AQ_PG_IMAGE_DIGEST": DIGEST}) == {"declared_digest": DIGEST, "verified_by_docker": False}
    assert P0.database_image({"AQ_PG_IMAGE_DIGEST": "pgvector/pgvector@" + DIGEST})["declared_digest"].endswith(DIGEST)


def test_a_declared_digest_is_checked_against_docker_when_a_container_is_named(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = DIGEST if cmd[1] == "inspect" else "pgvector/pgvector@" + DIGEST + " "
        return subprocess.CompletedProcess(cmd, 0, stdout=out + "\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    res = P0.database_image({"AQ_PG_IMAGE_DIGEST": DIGEST, "AQ_PG_CONTAINER": "c1"})
    assert res["verified_by_docker"] is True and res["docker_image_id"] == DIGEST and len(calls) == 2
    with pytest.raises(RuntimeError, match="does not match"):
        P0.database_image({"AQ_PG_IMAGE_DIGEST": "sha256:" + "b" * 64, "AQ_PG_CONTAINER": "c1"})
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such container"))
    with pytest.raises(RuntimeError, match="docker"):
        P0.database_image({"AQ_PG_IMAGE_DIGEST": DIGEST, "AQ_PG_CONTAINER": "c1"})


def test_the_runner_records_the_executor_environment_as_an_immutable_artifact(tmp_path):
    cases = [{"id": "Q1", "family": "f", "question": "q", "atoms": []}]
    root = tmp_path / "repo"
    root.mkdir()
    files = {}
    for role in RUN.REQUIRED_ROLES:
        (root / f"{role}.txt").write_text(role)
        files[role] = f"{role}.txt"
    (root / "cases.json").write_text(json.dumps({"cases": cases}))
    cfg = {"arm": "P0"}
    (root / "p0.json").write_text(RUN.canonical(cfg))
    files.update({"cases": "cases.json", "p0_config": "p0.json"})
    manifest = RUN.build_manifest(root, files, purpose="rehearsal", seed=1, commit="c" * 40, cases_path="cases.json")
    (tmp_path / "m.json").write_text(RUN.canonical(manifest))

    class Ex:
        environment = {"database": {"server_version": "16"}, "embedding_model": {"revision": "r"}}  # noqa: RUF012

        def effective_config(self):
            return cfg

        def open(self):
            pass

        def run_case(self, c):
            return {"id": c["id"], "family": c["family"], "arm": "P0", "question": c["question"], "reply": "r", "manifest": {}}

        def close(self):
            pass

    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    auth = tmp_path / "a.json"
    auth.write_text(json.dumps({"decision": RUN.AUTH_DECISION, "manifest_sha256": RUN.manifest_sha256(manifest), "run_id": "r1", "authorized_by": "t", "single_use": True, "p0_model_calls_authorized": True, "purpose": "rehearsal",
                                "expires_at": (now + timedelta(hours=1)).isoformat()}))
    d = RUN.execute(tmp_path / "m.json", root, tmp_path / "runs", "r1", p0_executor=Ex(), candidate_arm=lambda cs: [{"id": c["id"], "family": c["family"], "arm": "d", "question": c["question"], "reply": "x", "manifest": {}, "outcome": {"atoms": []}} for c in cs],
                    authorization_path=auth, execute_flag=True, now=now, git=lambda r: {"head": "c" * 40, "dirty_tracked": []})
    assert json.loads((d / "p0_environment.json").read_text()) == Ex.environment
    assert "p0_environment.json" in (d / "ARTIFACTS.sha256").read_text()


# -- R2: offline mode ----------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_offline_mode_sets_both_variables_and_the_loaded_hub_constant_and_restores_them(monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "0")
    constants = pytest.importorskip("huggingface_hub.constants")
    before = constants.HF_HUB_OFFLINE
    constants.HF_HUB_OFFLINE = False
    try:
        saved = P0.set_offline()
        assert os.environ["HF_HUB_OFFLINE"] == "1" and os.environ["TRANSFORMERS_OFFLINE"] == "1" and constants.HF_HUB_OFFLINE is True
        P0.restore_offline(saved)
        assert "HF_HUB_OFFLINE" not in os.environ and os.environ["TRANSFORMERS_OFFLINE"] == "0" and constants.HF_HUB_OFFLINE is False
    finally:
        constants.HF_HUB_OFFLINE = before


def test_a_failed_open_leaves_the_process_environment_exactly_as_it_found_it(monkeypatch):
    for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "KBENCH_CORPUS", "AQ_PG_IMAGE_DIGEST"):
        monkeypatch.delenv(k, raising=False)
    ex = P0.RealP0Executor(SEL / "corpus_v4.json")
    with pytest.raises(RuntimeError, match="AQ_PG_IMAGE_DIGEST"):
        ex.open()  # production path: offline switched on, then the missing image digest fails the run
    assert all(k not in os.environ for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "KBENCH_CORPUS"))
    monkeypatch.setenv("KBENCH_CORPUS", "/previous.json")
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    with pytest.raises(RuntimeError):
        P0.RealP0Executor(SEL / "corpus_v4.json").open()
    assert os.environ["KBENCH_CORPUS"] == "/previous.json" and os.environ["HF_HUB_OFFLINE"] == "0"


def _isolated(code: str, **env):
    full = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path), **env}
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True, env=full, timeout=300, check=False)


CACHED = (Path.home() / ".cache" / "huggingface" / "hub" / "models--sentence-transformers--all-MiniLM-L6-v2").exists()


@pytest.mark.skipif(not CACHED, reason="the embedding model is not cached on this machine")
def test_the_cached_embedding_model_loads_offline_with_no_outbound_connection():
    code = f"""
        import socket, sys
        sys.path[:0] = [{str(SEL)!r}, {str(SEL.parent)!r}, {str(KB)!r}]
        attempts = []
        real = socket.socket.connect
        def guard(self, address):
            attempts.append(address)
            raise OSError("no connection allowed")
        socket.socket.connect = guard
        import dev16_p0 as p0
        saved = p0.set_offline()
        ident = p0.embedding_identity()
        from companion_core.rag import embeddings
        vec = embeddings.embed(["a short probe sentence"])
        p0.restore_offline(saved)
        print(len(vec[0]), ident["revision"], len(ident["weights_sha256"]), len(attempts))
    """
    res = _isolated(code)
    assert res.returncode == 0, res.stderr[-800:]
    dim, revision, hashlen, attempts = res.stdout.split()[-4:]
    assert dim == "384" and len(revision) == 40 and hashlen == "64" and attempts == "0"


def test_a_missing_cached_dependency_fails_closed_without_downloading(tmp_path):
    code = f"""
        import socket, sys
        sys.path[:0] = [{str(SEL)!r}, {str(SEL.parent)!r}, {str(KB)!r}]
        attempts = []
        def guard(self, address):
            attempts.append(address)
            raise OSError("no connection allowed")
        socket.socket.connect = guard
        import dev16_p0 as p0
        p0.set_offline()
        try:
            p0.embedding_identity()
            print("LOADED", len(attempts))
        except Exception as exc:
            print("FAILED_CLOSED", type(exc).__name__, len(attempts))
    """
    res = _isolated(code, HF_HOME=str(tmp_path / "empty-hf-home"), HF_HUB_CACHE=str(tmp_path / "empty-hf-home" / "hub"))
    assert res.returncode == 0, res.stderr[-800:]
    assert "FAILED_CLOSED" in res.stdout and res.stdout.split()[-1] == "0"


# -- R3: independent builds are identical (database-backed; skipped without a disposable server) ------------------------------------------------------------------------------------------

needs_db = pytest.mark.skipif(not os.environ.get("KBENCH_DATABASE_URL"), reason="set KBENCH_DATABASE_URL to a DISPOSABLE PostgreSQL with pgvector")


@needs_db
def test_two_independent_builds_have_identical_ids_and_identical_ordered_search_results_where_random_ids_do_not():
    sys.path[:0] = [str(SEL), str(SEL.parent), str(KB)]
    try:
        repro = _load("dev16_p0_tiebreak_probe")
    finally:
        del sys.path[:3]
    out = SEL.parent / "results"  # unused: the probe returns its report
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / f"tiebreak-{uuid.uuid4().hex[:8]}.json"
    stable = asyncio.run(repro.main(tmp, True))
    assert stable["results"]["store_ids_identical_across_builds"] == 1 and stable["results"]["sequences_differ"] == 0 and stable["results"]["P5_cut_membership_differs"] == 0 and stable["results"]["P1_scores_identical"] == stable["results"]["queries"] == 173
    random = asyncio.run(repro.main(tmp, False))  # the negative control: with random ids the same probe sees the jitter
    assert random["results"]["store_ids_identical_across_builds"] == 0 and random["results"]["sequences_differ"] > 100 and random["results"]["differences_outside_tie_groups"] == 0
    tmp.unlink(missing_ok=True)
    assert out.exists()
