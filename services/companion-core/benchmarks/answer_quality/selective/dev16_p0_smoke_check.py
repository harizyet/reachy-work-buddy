"""Check the output of the development-only P0 smoke test against the declared acceptance schema and the access rules (Phase 44, 2026-10-10). Reads the smoke run directory only; consumed dev15 data only; no model call.

    python dev16_p0_smoke_check.py <smoke-output-dir> <pg-image-digest> <pg-version>
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIG = list(sys.argv)
sys.path.insert(0, str(HERE))
import dev16_candidate_arm as ca
import dev16_runner as r

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def main(out: Path, pg_digest: str, pg_version: str) -> dict:
    run = out / "runs" / "smoke-dev15-1"
    rows = r.read_jsonl(run / "p0_rows.jsonl")
    cand = {x["id"]: x for x in r.read_jsonl(run / "candidate_rows.jsonl")}
    cases = {c["id"]: c for c in json.loads((out / "cases_smoke_dev15.json").read_text())["cases"]}
    decl = json.loads((HERE / "dev16_p0_config.json").read_text())
    fields = decl["output_schema"]["row"]
    _world, meta, profiles = ca.load_world(HERE / "corpus_v4.json")
    pilot = {x["id"]: x for x in json.loads((HERE.parent / "results" / "pilot-dev15-7b.json").read_text())["rows"] if x["arm"] == "b1a"}
    prov = json.loads((run / "provenance.json").read_text())
    problems, per_case = [], []
    if [x["id"] for x in rows] != list(cases):
        problems.append("P0 rows do not cover the smoke cases in order")
    for x in rows:
        c = cases[x["id"]]
        viol = ca.record_violations(meta, profiles[c["access"]])
        miss = [f for f in fields if f not in x]
        extra = [f for f in x if f not in fields]
        cited = sorted(set(re.findall(r"\[(E\d+)\]", x["reply"])))
        refs = [ref for e in x["manifest"].values() for ref in e["refs"]]
        bad_refs = {ref: viol(ref) for ref in refs if viol(ref)}
        unauth = [e for e, v in x["manifest"].items() if not v["authorized"]]
        row = {"id": x["id"], "access": c["access"], "family": c["family"], "latency_ms": x["ms"], "prompt_tokens": x["prompt_tokens"], "completion_tokens": x["completion_tokens"], "finish_reason": x["finish_reason"],
               "evidence_entries": len(x["manifest"]), "retrieved_refs": sorted(set(refs)), "reply_cites": cited, "cites_not_in_manifest": [e for e in cited if e not in x["manifest"]], "violations": bad_refs, "unauthorised_entries": unauth,
               "missing_fields": miss, "extra_fields": extra, "messages_sha256_ok": bool(HEX64.match(x["messages_sha256"])), "arm_ok": x["arm"] == "P0", "family_matches_case": x["family"] == c["family"], "question_matches_case": x["question"] == c["question"],
               "reproduces_pilot_reply": (x["reply"] == pilot[x["id"]]["reply"]) if x["id"] in pilot else None, "candidate_cited_refs": sorted({ref for e in cand[x["id"]]["manifest"].values() for ref in e["refs"]})}
        per_case.append(row)
        for key in ("missing_fields", "extra_fields", "cites_not_in_manifest", "unauthorised_entries"):
            if row[key]:
                problems.append(f"{x['id']}: {key} {row[key]}")
        if bad_refs:
            problems.append(f"{x['id']}: retrieved records outside the access profile {bad_refs}")
        if not (row["messages_sha256_ok"] and row["arm_ok"] and row["family_matches_case"] and row["question_matches_case"]):
            problems.append(f"{x['id']}: schema value check failed")
        if x["finish_reason"] not in ("stop", "length"):
            problems.append(f"{x['id']}: unexpected finish_reason {x['finish_reason']}")
    shared = next(p for p in per_case if p["access"] == "shared_speaker")
    harbor = next(p for p in per_case if p["access"] == "harbor_only")
    lat = [p["latency_ms"] for p in per_case]
    base = [p for p in per_case if p["reproduces_pilot_reply"] is not None]
    report = {"purpose": "development-only smoke test of the real P0 path on consumed dev15 cases; not an acceptance artifact; nothing here is a result about any system", "ok": not problems, "problems": problems,
              "cases": len(rows), "state": json.loads((run / "STATE.json").read_text())["state"], "errors": 0 if (run / "failure.json").exists() is False else 1,
              "latency_ms": {"min": min(lat), "median": statistics.median(lat), "max": max(lat), "total": sum(lat)}, "finish_reasons": sorted({p["finish_reason"] for p in per_case}),
              "access_enforcement": {"shared_speaker_variant_retrieved_records": len(shared["retrieved_refs"]), "harbor_only_variant_retrieved_records": harbor["retrieved_refs"], "any_record_outside_profile": any(p["violations"] for p in per_case)},
              "pilot_reproduction": {"compared": len(base), "identical_replies": sum(bool(p["reproduces_pilot_reply"]) for p in base)},
              "provenance": {"git_head": prov["git"]["head"], "manifest_sha256": prov["manifest_sha256"], "authorization_sha256": prov["authorization_sha256"], "p0_config_sha256": prov["manifest"]["files"]["p0_config"]["sha256"],
                             "p0_effective_config_matches_declared": prov["p0_effective_config"] == json.loads((HERE / "dev16_p0_config.json").read_text()), "mode": prov["mode"], "env": prov["env"], "python": prov["python"].split()[0],
                             "postgres": {"image_digest": pg_digest, "version": pg_version, "disposable": True}, "retrieval_corpus": "selective/corpus_v4.json (the invented corpus; no private user records)"},
              "per_case": per_case}
    (out / "SMOKE_REPORT.json").write_text(json.dumps(report, indent=1, default=str))
    return report


if __name__ == "__main__":
    rep = main(Path(ORIG[1]), ORIG[2], ORIG[3])
    print(json.dumps({k: rep[k] for k in ("ok", "problems", "cases", "state", "errors", "latency_ms", "finish_reasons", "access_enforcement", "pilot_reproduction")}, indent=1))
