"""Verification of the corrected-P0 development smoke test (Phase 44, 2026-10-10): schema, citations, access, environment record, and a cross-check that the run's prepared evidence and prompt hashes equal the
deterministic reproducibility evidence. Consumed dev15 cases only; no generation call (the only server contact is the tokenizer endpoint, which is what the context builder itself uses).

Cross-check: the ten cases are PREPARED again (retrieval, access context, prompt assembly; no model generation) in a fresh stable-id database (a) with the same live tokenizer the run used, which must reproduce the run's
ordered evidence AND message hashes exactly, and (b) in a second fresh database with the offline deterministic counter used by the reproducibility evidence, which must reproduce the run's ordered evidence (token
packing may legitimately differ between a real and an approximate counter; any difference is reported with its cause, not hidden).

    python dev16_p0_smoke2_check.py <smoke2-output-dir>      (KBENCH_DATABASE_URL, AQ_PG_IMAGE_DIGEST, AQ_PG_CONTAINER as for the run)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIG = list(sys.argv)
sys.path[:0] = [str(HERE), str(HERE.parent), str(HERE.parents[1] / "knowledge_retrieval")]
import dev16_candidate_arm as ca
import dev16_p0 as p0
import dev16_runner as r

HEX64 = re.compile(r"^[0-9a-f]{64}$")


async def prepare_all(cases: list[dict], counter) -> dict:
    from aq.conditions_g2 import GConditions2
    from companion_core.rag import embeddings
    from kbench.corpus import build_corpus
    from kbench.pg_env import build_pg_corpus
    from validate_scorer import PEOPLE

    spec = (await build_corpus()).spec
    embeddings.embed(["warm up"])
    env = await build_pg_corpus(spec, embeddings.embed, embeddings._MODEL_NAME, stable=True)
    runner = GConditions2(env, spec, counter, budget=p0.DECLARED["harness"]["budget_tokens"], minilm_embed=embeddings.embed)
    runner.people = PEOPLE
    out = {}
    for c in cases:
        prep = await runner.prepare("b1a", c)
        ev = [(eid, tuple(e.refs), bool(e.authorized)) for eid, e in sorted(prep.evidence.items(), key=lambda kv: int(kv[0][1:]))]
        out[c["id"]] = {"evidence": ev, "messages_sha256": hashlib.sha256(json.dumps(prep.messages, sort_keys=True).encode()).hexdigest()}
    await env.close()
    return out


def main(out: Path) -> dict:
    os.environ["HF_HUB_OFFLINE"] = os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("KBENCH_CORPUS", str(HERE / "corpus_v4.json"))
    from aq import llm as llmlib
    from dev16_p0_reproducibility import OfflineCounter

    run = out / "runs" / "smoke2-corrected-1"
    rows = r.read_jsonl(run / "p0_rows.jsonl")
    cases = json.loads((out / "cases_smoke_dev15.json").read_text())["cases"]
    prov = json.loads((run / "provenance.json").read_text())
    envart = json.loads((run / "p0_environment.json").read_text())
    decl = json.loads((HERE / "dev16_p0_config.json").read_text())
    fields = decl["output_schema"]["row"]
    _w, meta, profiles = ca.load_world(HERE / "corpus_v4.json")
    problems, per_case = [], []
    if [x["id"] for x in rows] != [c["id"] for c in cases]:
        problems.append("P0 rows do not cover the ten cases in order")
    by_case = {c["id"]: c for c in cases}
    for x in rows:
        c = by_case[x["id"]]
        viol = ca.record_violations(meta, profiles[c["access"]])
        refs = [ref for e in x["manifest"].values() for ref in e["refs"]]
        cited = sorted(set(re.findall(r"\[(E\d+)\]", x["reply"])))
        row = {"id": x["id"], "access": c["access"], "family": c["family"], "latency_ms": x["ms"], "prompt_tokens": x["prompt_tokens"], "completion_tokens": x["completion_tokens"], "finish_reason": x["finish_reason"], "evidence_entries": len(x["manifest"]),
               "retrieved_refs": sorted(set(refs)), "reply_cites": cited, "cites_not_in_manifest": [e for e in cited if e not in x["manifest"]], "violations": {ref: viol(ref) for ref in refs if viol(ref)},
               "unauthorised_entries": [e for e, v in x["manifest"].items() if not v["authorized"]], "missing_fields": [f for f in fields if f not in x], "extra_fields": [f for f in x if f not in fields],
               "messages_sha256": x["messages_sha256"], "messages_sha256_ok": bool(HEX64.match(x["messages_sha256"])), "arm_ok": x["arm"] == "P0", "question_ok": x["question"] == c["question"], "family_ok": x["family"] == c["family"]}
        per_case.append(row)
        for key in ("missing_fields", "extra_fields", "cites_not_in_manifest", "unauthorised_entries", "violations"):
            if row[key]:
                problems.append(f"{x['id']}: {key} {row[key]}")
        if not (row["messages_sha256_ok"] and row["arm_ok"] and row["question_ok"] and row["family_ok"]) or x["finish_reason"] not in ("stop", "length"):
            problems.append(f"{x['id']}: schema value check failed")
    # environment record
    db = envart["database"]
    expected_image = os.environ.get("AQ_PG_IMAGE_DIGEST", "")
    env_ok = {"image_digest_matches_declared": db["declared_digest"] == expected_image != "", "verified_by_docker": db["verified_by_docker"] is True, "postgres_version": db["server_version"], "pgvector": db["pgvector_extension"],
              "stable_ids": "stable" in db["record_ids"], "pg_env_sha_matches_file": db["pg_env_sha256"] == hashlib.sha256((HERE.parents[1] / "knowledge_retrieval" / "kbench" / "pg_env.py").read_bytes()).hexdigest(),
              "embedding": envart["embedding_model"], "offline_flags": envart["offline"], "served_models_ids": [m["id"] for m in envart["served_models_response"]["data"]], "served_model_root": envart["served_models_response"]["data"][0].get("root"),
              "max_model_len": envart["served_models_response"]["data"][0].get("max_model_len"), "p0_effective_config_matches_declared": prov["p0_effective_config"] == decl, "git_head": prov["git"]["head"], "mode": prov["mode"], "seed_in_manifest": prov["manifest"]["seed"]}
    if not (env_ok["image_digest_matches_declared"] and env_ok["verified_by_docker"] and env_ok["stable_ids"] and env_ok["pg_env_sha_matches_file"] and env_ok["p0_effective_config_matches_declared"] and env_ok["offline_flags"] == {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}):
        problems.append(f"environment record check failed: {env_ok}")
    # cross-check against deterministic re-preparation (no generation)
    live = asyncio.run(prepare_all(cases, llmlib.Local()))
    stub = asyncio.run(prepare_all(cases, OfflineCounter()))
    run_ev = {x["id"]: [(k, tuple(x["manifest"][k]["refs"]), bool(x["manifest"][k]["authorized"])) for k in sorted(x["manifest"], key=lambda k: int(k[1:]))] for x in rows}
    cross = {"live_tokenizer_fresh_build_same_ordered_evidence": sum(live[i]["evidence"] == run_ev[i] for i in run_ev), "live_tokenizer_fresh_build_same_message_hash": sum(live[i]["messages_sha256"] == next(x["messages_sha256"] for x in rows if x["id"] == i) for i in run_ev),
             "offline_counter_fresh_build_same_ordered_evidence": sum(stub[i]["evidence"] == run_ev[i] for i in run_ev), "cases": len(run_ev), "offline_counter_differences": []}
    for i, expected in run_ev.items():
        if stub[i]["evidence"] != expected:
            a, b = [e[1] for e in expected], [e[1] for e in stub[i]["evidence"]]
            cross["offline_counter_differences"].append({"id": i, "run_entries": len(a), "offline_entries": len(b), "offline_is_extension_or_prefix_of_run": b[:len(a)] == a or a[:len(b)] == b, "same_order_on_common_prefix": a[:min(len(a), len(b))] == b[:min(len(a), len(b))]})
    if cross["live_tokenizer_fresh_build_same_ordered_evidence"] != len(run_ev) or cross["live_tokenizer_fresh_build_same_message_hash"] != len(run_ev):
        problems.append(f"the run does not reproduce under the same tokenizer: {cross}")
    lat = [p["latency_ms"] for p in per_case]
    report = {"purpose": "corrected-P0 development smoke test verification; consumed dev15 cases; not an acceptance artifact; no statement about any system's quality", "ok": not problems, "problems": problems, "cases": len(rows),
              "state": json.loads((run / "STATE.json").read_text())["state"], "errors": int((run / "failure.json").exists()), "latency_ms": {"min": min(lat), "median": statistics.median(lat), "max": max(lat), "total": sum(lat)},
              "finish_reasons": sorted({p["finish_reason"] for p in per_case}), "access_variants": {p["id"]: {"access": p["access"], "retrieved": p["retrieved_refs"]} for p in per_case if p["access"] != "owner_private"},
              "environment": env_ok, "cross_check_against_deterministic_preparation": cross, "per_case": per_case}
    (out / "SMOKE2_REPORT.json").write_text(json.dumps(report, indent=1, default=str))
    return report


if __name__ == "__main__":
    rep = main(Path(ORIG[1]))
    print(json.dumps({k: rep[k] for k in ("ok", "problems", "cases", "state", "errors", "latency_ms", "finish_reasons", "access_variants", "cross_check_against_deterministic_preparation")}, indent=1))
    print(json.dumps(rep["environment"], indent=1))
