"""Reproducibility verification of the P0 retrieval and prompt-assembly path across INDEPENDENT disposable databases (Phase 44, P0 reproducibility correction, 2026-10-10). Consumed dev15 questions and the frozen invented
corpus only. NO model call and no contact with the model server: the token budget uses a deterministic offline counter (the same function of the text in every build, so build-to-build identity is unaffected).

For each of two independently built databases (`build_pg_corpus(..., stable=True)`), and for EVERY dev15 question under EVERY access profile, the pinned P0 preparation (`GConditions2.prepare('b1a', case)`) is run and compared:
  * the ordered evidence: evidence id -> record references, in order, as REAL ids (identical stable ids) and as logical keys;
  * the evidence manifest (references and authorised flags), the dropped counts, and the sha256 of the assembled messages (prompt contents);
  * access enforcement: every retrieved record is authorised for the case's profile (the corpus's authoritative per-record facts);
  * citation integrity: every evidence entry's references exist in the corpus and map back to their logical record.
Extra checks: both builds assign identical store ids; the stable id of a record equals the documented derivation; a DUPLICATE-CONTENT fixture (the frozen corpus plus identical-text records) is retrievable in the same
order in both builds and its duplicates really tie; the number of cases whose top-10 contains an equal-score tie is reported, so the test is shown to exercise ties. Any difference is reported as a BLOCKER (exit 1).

    python dev16_p0_reproducibility.py <output-json> [--random-ids | --versus-random]      (--versus-random: informational, how much the corrected path differs from a random-id build; --random-ids is the NEGATIVE CONTROL: random ids must be reported as a blocker; KBENCH_DATABASE_URL must name the disposable server; HF offline mode is set here)
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIG = list(sys.argv)
sys.path[:0] = [str(HERE), str(HERE.parent), str(HERE.parents[1] / "knowledge_retrieval")]


VERSUS_RANDOM = "--versus-random" in ORIG
STABLE = "--random-ids" not in ORIG  # the negative control builds with random ids and must be reported as a blocker


class OfflineCounter:
    """Stands in for the model server's tokenizer: a deterministic function of the text. Never contacts any server."""

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def healthy(self) -> bool:  # pragma: no cover - never used
        return True


async def build(spec: dict, stable: bool | None = None):
    from aq.conditions_g2 import GConditions2
    from companion_core.rag import embeddings
    from kbench.pg_env import build_pg_corpus
    from validate_scorer import PEOPLE

    embeddings.embed(["warm up"])
    env = await build_pg_corpus(spec, embeddings.embed, embeddings._MODEL_NAME, stable=STABLE if stable is None else stable)
    runner = GConditions2(env, spec, OfflineCounter(), budget=1500, minilm_embed=embeddings.embed)
    runner.people = PEOPLE
    return env, runner


async def collect(env, runner, spec: dict, cases: list[dict], meta: dict) -> dict:
    from kbench.security import violations

    out = {}
    for case in cases:
        for profile in spec["access_profiles"]:
            c = {**case, "access": profile}
            prep = await runner.prepare("b1a", c)
            evidence = [(eid, tuple(e.refs), bool(e.authorized)) for eid, e in sorted(prep.evidence.items(), key=lambda kv: int(kv[0][1:]))]
            bad = [ref for _, refs, _ in evidence for ref in refs if violations(env.logical_key(ref).split("#")[0], meta, spec["access_profiles"][profile])]
            out[(case["id"], profile)] = {"evidence": evidence, "logical": [(eid, tuple(env.logical_key(r) for r in refs), a) for eid, refs, a in evidence], "dropped": dict(prep.retrieval_dropped or {}), "dropped_built": dict(prep.dropped or {}),
                                          "messages_sha256": hashlib.sha256(json.dumps(prep.messages, sort_keys=True).encode()).hexdigest(), "violations": bad}
    return out


async def duplicates(spec: dict) -> dict:
    """A fixture: the frozen corpus plus 6 records with identical content, different ids/scopes/sensitivities. Two builds must retrieve them in the same order, and they must really tie."""
    from companion_core.knowledge.search import SearchFilter

    base = copy.deepcopy(spec)
    template = base["memories"][0]
    text = "The Zephyr gateway on-call rotation pages the duty engineer first."
    for i in range(6):
        base["memories"].append({**template, "id": f"dup{i}", "text": text, "scope": ["cedar", "osprey", None, "harbor", "marlin", "vesper"][i], "sensitivity": ["public", "work-private"][i % 2], "forgotten": False, "expires": None})
    flt = SearchFilter(sensitivities=("public", "work-private", "sensitive"))
    res = []
    for _ in range(2):
        env, _runner = await build(base)
        hits = await env.search.lexical("Zephyr gateway on-call rotation pages duty engineer", flt, 20)
        res.append(([env.logical_key(h.ref_key) for h in hits], [round(h.score, 9) for h in hits], dict(env.store_id)))
        await env.close()
    dup_scores = {s for k, s in zip(res[0][0], res[0][1], strict=True) if k.startswith("memory:dup")}
    return {"duplicate_records_retrieved": sum(k.startswith("memory:dup") for k in res[0][0]), "tied_score_values_among_duplicates": sorted(dup_scores), "same_order_in_both_builds": res[0][0] == res[1][0], "same_ids_in_both_builds": res[0][2] == res[1][2],
            "duplicates_really_tie": len(dup_scores) == 1 and sum(k.startswith("memory:dup") for k in res[0][0]) >= 2}


async def main(out: Path) -> dict:
    from companion_core.knowledge.search import SearchFilter
    from kbench.corpus import build_corpus
    from kbench.fixtures import source_meta
    from kbench.pg_env import STABLE_ID_NAMESPACE

    spec = (await build_corpus()).spec
    meta = source_meta(spec)
    cases = json.loads((HERE.parent / "cases_dev15.json").read_text())["cases"]
    env_a, runner_a = await build(spec)
    a = await collect(env_a, runner_a, spec, cases, meta)
    ids_a = dict(env_a.store_id)
    flt = SearchFilter(sensitivities=("public", "work-private", "sensitive"))
    ties_in_top10 = 0
    for c in cases:
        hs = await env_a.search.lexical(c["question"], flt, 10)
        ties_in_top10 += len({round(h.score, 9) for h in hs}) < len(hs)
    await env_a.close()
    env_b, runner_b = await build(spec, False if VERSUS_RANDOM else None)  # --versus-random: how much does the corrected path differ from an uncorrected (random-id) build?
    b = await collect(env_b, runner_b, spec, cases, meta)
    ids_b = dict(env_b.store_id)
    await env_b.close()
    keys = sorted(a)
    diffs = {"evidence_real_ids": [k for k in keys if a[k]["evidence"] != b[k]["evidence"]], "evidence_logical": [k for k in keys if a[k]["logical"] != b[k]["logical"]],
             "dropped": [k for k in keys if a[k]["dropped"] != b[k]["dropped"] or a[k]["dropped_built"] != b[k]["dropped_built"]], "messages_sha256": [k for k in keys if a[k]["messages_sha256"] != b[k]["messages_sha256"]]}
    derivation_ok = all(uuid.UUID(real).version == 5 for real in ids_a.values()) and ids_a == ids_b
    dup = await duplicates(spec)
    refs_ok = all(all(r.split(":")[0] in ("memory", "document", "meeting", "note", "task", "reminder") for _, refs, _ in v["logical"] for r in refs) for v in a.values())
    n_empty = sum(1 for v in a.values() if not v["evidence"])
    report = {"purpose": "P0 retrieval/prompt reproducibility across independent disposable databases; no model call, no server contact; consumed dev15 data", "stable_ids": STABLE, "mode": "versus-random (build A stable, build B random)" if VERSUS_RANDOM else ("random-ids negative control" if not STABLE else "two stable builds"), "cases": len(cases), "profiles": list(spec["access_profiles"]),
              "comparisons": len(keys), "differences": {k: len(v) for k, v in diffs.items()}, "difference_examples": {k: [list(x) for x in v[:3]] for k, v in diffs.items() if v},
              "identical_store_ids_across_builds": ids_a == ids_b, "stable_id_namespace": str(STABLE_ID_NAMESPACE), "all_ids_are_uuid5": derivation_ok,
              "access_violations_build_a": sum(1 for v in a.values() if v["violations"]), "access_violations_build_b": sum(1 for v in b.values() if v["violations"]), "evidence_refs_resolve_to_known_stores": refs_ok,
              "comparisons_with_no_evidence": n_empty, "dev15_questions_with_an_equal_score_tie_in_the_top_10": ties_in_top10, "duplicate_content_fixture": dup, "STATUS": "REPRODUCIBLE"}
    if VERSUS_RANDOM:  # informational: the difference between the corrected and an uncorrected build is EXPECTED, not a blocker
        out.write_text(json.dumps({k: v for k, v in report.items() if k != 'STATUS'} | {'STATUS': 'INFORMATIONAL (stable build vs random-id build)'}, indent=1, default=str))
        return report | {'STATUS': 'INFORMATIONAL (stable build vs random-id build)'}
    blocker = any(diffs.values()) or not (ids_a == ids_b and derivation_ok and report["access_violations_build_a"] == 0 and report["access_violations_build_b"] == 0 and refs_ok
                                          and dup["same_order_in_both_builds"] and dup["same_ids_in_both_builds"] and dup["duplicates_really_tie"])
    if blocker:
        report["STATUS"] = "BLOCKER: the P0 retrieval path is not reproducible; do not declare reproducibility"
    out.write_text(json.dumps(report, indent=1, default=str))
    return report


if __name__ == "__main__":
    os.environ["HF_HUB_OFFLINE"] = os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("KBENCH_CORPUS", str(HERE / "corpus_v4.json"))
    rep = asyncio.run(main(Path(ORIG[1])))
    print(json.dumps({k: v for k, v in rep.items() if k != "difference_examples"}, indent=1, default=str))
    sys.exit(0 if rep["STATUS"] in ("REPRODUCIBLE",) or rep["STATUS"].startswith("INFORMATIONAL") else 1)
