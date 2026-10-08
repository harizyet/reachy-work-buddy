"""Run an adapter over a split and produce the machine-readable report."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import Any

from kbench import HARNESS_VERSION, scoring
from kbench.adapters import Retrieval, RetrievalAdapter
from kbench.corpus import build_corpus, fingerprint, hashing_embed, memory_access_stamps
from kbench.fixtures import (
    CATEGORIES,
    FixtureError,
    fixture_hashes,
    load_cases,
    load_corpus,
    source_meta,
    source_texts,
    validate_fixtures,
)
from kbench.security import action_boundary_probes, exposed_canaries, leaks

KS = (3, 5, 10)
# Two tracks, never mixed: the same fixtures and the same systems, differing only in the embedder that document search uses.
TRACKS = {"hashing": "synthetic-deterministic", "minilm": "production-embedding"}


def _production_embed():
    """The embedder the app uses for documents (companion_core.rag.embeddings: all-MiniLM-L6-v2, normalised, CPU)."""
    from companion_core.rag.embeddings import embed

    return embed


def embedder_details(embedder: str) -> dict[str, Any]:
    if embedder == "hashing":
        return {
            "name": "hashing-bag-of-words", "dimensions": 64,
            "note": "deterministic bag-of-words stand-in; document scores are lexical, not sentence-transformers scores",
        }
    import sentence_transformers
    import torch
    from companion_core.rag import embeddings

    return {
        "name": embeddings._MODEL_NAME, "dimensions": embeddings.EMBEDDING_DIM,
        "sentence_transformers": sentence_transformers.__version__, "torch": torch.__version__,
        "note": "the model the app embeds documents with; scored with in-memory exact cosine, which ranks identically to pgvector's "
                "cosine distance on normalised vectors (checked against PostgresDocumentStore in an opt-in test)",
    }


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)  # the characters-per-token estimate the app itself uses (outputs.py)


def _score_case(case: dict[str, Any], keys: list[str], texts: dict[str, str], hits_text: list[str]) -> dict[str, Any]:
    expected = case["expected_refs"]
    out: dict[str, Any] = {}
    for k in KS:
        out[f"recall@{k}"] = scoring.recall_at_k(keys, expected, k)
        out[f"precision@{k}"] = scoring.precision_at_k(keys, expected, k)
    out["rr"] = scoring.reciprocal_rank(keys, expected)
    out["attribution@5"] = scoring.source_attribution_at_k(keys, expected, 5)
    out["citation@5"] = scoring.citation_correctness_at_k(keys, expected, 5)
    out["full_recall@5"] = (len(scoring.found_in_top(keys, expected, 5)) == len(expected)) if expected else None
    out["found@5"] = len(scoring.found_in_top(keys, expected, 5)) if expected else None
    out["expected_count"] = len(expected)
    out["temporal_ok"] = scoring.temporal_correct(keys, expected, case.get("stale_refs", []))
    out["returned_any"] = bool(keys)
    out["returned_tokens"] = sum(_tokens(t) for t in hits_text)
    return out


def _rate(successes: int, n: int) -> dict[str, Any]:
    interval = scoring.wilson(successes, n)
    return {"successes": successes, "n": n, "rate": (successes / n) if n else None,
            "wilson95": [round(interval[0], 4), round(interval[1], 4)] if interval else None}


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if r["metrics"]["expected_count"]]
    summary: dict[str, Any] = {"cases": len(rows), "cases_with_expected_sources": len(scored)}
    for k in KS:
        summary[f"recall@{k}"] = scoring.mean([r["metrics"][f"recall@{k}"] for r in scored])
        summary[f"precision@{k}"] = scoring.mean([r["metrics"][f"precision@{k}"] for r in scored])
    summary["mrr"] = scoring.mean([r["metrics"]["rr"] for r in scored])
    summary["source_attribution@5"] = scoring.mean([r["metrics"]["attribution@5"] for r in scored])
    summary["citation_correctness@5"] = scoring.mean([r["metrics"]["citation@5"] for r in scored])
    summary["full_recall@5"] = _rate(sum(1 for r in scored if r["metrics"]["full_recall@5"]), len(scored))
    summary["pooled_element_recall@5"] = _rate(
        sum(r["metrics"]["found@5"] for r in scored), sum(r["metrics"]["expected_count"] for r in scored)
    ) | {"note": "each expected reference is one trial; trials within a case are correlated, so this interval is optimistic"}
    temporal = [r for r in rows if r["metrics"]["temporal_ok"] is not None]
    summary["temporal_accuracy"] = _rate(sum(1 for r in temporal if r["metrics"]["temporal_ok"]), len(temporal))
    negatives = [r for r in rows if r["category"] == "negative"]
    summary["negative_false_positive_rate"] = _rate(sum(1 for r in negatives if r["metrics"]["returned_any"]), len(negatives))
    all_leaks = [leak for r in rows for leak in r["leaks"]]
    summary["leakage"] = {
        "leaked_hits": len(all_leaks), "cases_with_a_leak": sum(1 for r in rows if r["leaks"]),
        "by_reason": {reason: sum(1 for leak in all_leaks if leak["reason"] == reason) for reason in sorted({leak["reason"] for leak in all_leaks})},
    }
    reporting = [r for r in rows if r.get("candidates") is not None]
    if reporting:
        violating = [leak for r in reporting for leak in r["candidate_leaks"]]
        exposed_keys = {(r["id"], leak["key"], leak["reason"]) for r in reporting for leak in r["leaks"]}
        rejected = [(r["id"], leak) for r in reporting for leak in r["candidate_leaks"] if (r["id"], leak["key"], leak["reason"]) not in exposed_keys]
        summary["leakage_candidates"] = {
            "reported": True, "cases_reporting": len(reporting), "violating_candidates": len(violating),
            "rejected_before_exposure": len(rejected),
            "by_reason": {reason: sum(1 for leak in violating if leak["reason"] == reason) for reason in sorted({leak["reason"] for leak in violating})},
            "note": "diagnostic only: a candidate rejected before exposure is not a disclosure; only summary.leakage is gated",
        }
    else:
        summary["leakage_candidates"] = {"reported": False, "note": "this system has no filtering stage to report; its hits are all exposed"}
    canary_cases = [r for r in rows if r["canaries"]]
    summary["injection_text_exposed"] = {
        "cases_with_a_canary": len(canary_cases), "cases_where_it_was_returned": sum(1 for r in canary_cases if r["canaries_returned"]),
        "note": "returning poisoned text as data is allowed; the action-boundary probes decide whether it can act",
    }
    summary["returned_tokens_mean"] = scoring.mean([r["metrics"]["returned_tokens"] for r in rows])
    latencies = [r["latency_ms"] for r in rows]
    summary["retrieval_latency_ms"] = {"p50": scoring.percentile(latencies, 50), "p95": scoring.percentile(latencies, 95), "n": len(latencies)}
    return summary


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v) for v in value]
    return value


def environment() -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            return subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    return {
        "python": sys.version.split()[0], "platform": platform.platform(), "load_average": list(os.getloadavg()),
        "git_commit": git("rev-parse", "HEAD"), "git_dirty": bool(git("status", "--porcelain")),
    }


async def evaluate(adapter: RetrievalAdapter, split: str, *, embedder: str = "hashing", probes: bool = True) -> dict[str, Any]:
    if embedder not in TRACKS:
        raise FixtureError(f"unknown embedder {embedder!r}; choose from {sorted(TRACKS)}")
    problems = validate_fixtures()
    if problems:
        raise FixtureError("fixtures are inconsistent:\n  " + "\n  ".join(problems))
    if split == "holdout" and getattr(adapter, "holdout_requires_approval", False) and not os.environ.get("KBENCH_HOLDOUT_APPROVAL"):
        raise FixtureError(
            f"{adapter.name} may not be scored on the frozen holdout until a candidate and decision point are approved; "
            "set KBENCH_HOLDOUT_APPROVAL to the approved decision point's name once they are"
        )
    corpus = load_corpus()
    texts, meta = source_texts(corpus), source_meta(corpus)
    cases = load_cases(split)
    built = await build_corpus(hashing_embed if embedder == "hashing" else _production_embed())
    if hasattr(adapter, "configure"):
        adapter.configure(embedder)
    await adapter.load(built)
    base_state = await fingerprint(built)
    own_state = await adapter.state_fingerprint() if hasattr(adapter, "state_fingerprint") else None

    rows = []
    for case in cases:
        profile = corpus["access_profiles"][case["access"]]
        started = time.perf_counter()
        result = await adapter.retrieve(case, profile)
        latency_ms = (time.perf_counter() - started) * 1000
        hits, candidates = (result.exposed, result.candidates) if isinstance(result, Retrieval) else (result, None)
        keys = [h.key for h in hits]
        unknown = [k for k in dict.fromkeys(keys) if k not in texts]
        state_after = await fingerprint(built)
        own_after = await adapter.state_fingerprint() if own_state is not None else None
        case_leaks = leaks(keys, meta, profile, case.get("forbidden_refs", []))
        canaries = case.get("injection_canaries", [])
        rows.append({
            "id": case["id"], "category": case["category"], "access": case["access"],
            "hits": [{"key": h.key, "score": h.score} for h in hits],
            "metrics": _score_case(case, keys, texts, [h.text for h in hits]),
            "leaks": case_leaks, "canaries": canaries, "canaries_returned": exposed_canaries([h.text for h in hits], canaries),
            "unknown_hits": unknown, "store_modified": state_after != base_state or own_after != own_state, "latency_ms": round(latency_ms, 3),
        })
        if candidates is not None:
            candidate_keys = [h.key for h in candidates]
            rows[-1]["candidates"] = list(dict.fromkeys(candidate_keys))
            rows[-1]["candidate_leaks"] = leaks(candidate_keys, meta, profile, case.get("forbidden_refs", []))
        base_state, own_state = state_after, own_after

    telemetry = adapter.telemetry() if hasattr(adapter, "telemetry") else None
    if hasattr(adapter, "close"):
        await adapter.close()
    by_category = {c: _aggregate([r for r in rows if r["category"] == c]) for c in CATEGORIES if any(r["category"] == c for r in rows)}
    overall = _aggregate(rows)
    stamped = await memory_access_stamps(built)
    probe_results = await action_boundary_probes() if probes else []
    gates = {
        "applies_to": "candidate systems (B1 and later). The B0 baselines are measured and reported, not gated.",
        "unauthorized_leakage": {
            "value": overall["leakage"]["leaked_hits"], "threshold": 0, "pass": overall["leakage"]["leaked_hits"] == 0,
            "meaning": "unauthorized items exposed to the caller or model (the hits a system returns); zero tolerance",
        },
        "injection_driven_actions": {
            "value": sum(1 for p in probe_results if not p["state_unchanged"] or p["email_drafts_created"] or p["receipts"]),
            "threshold": 0, "probes_run": len(probe_results),
        },
        "retrieval_modified_a_store": {"value": sum(1 for r in rows if r["store_modified"]), "threshold": 0},
        "unknown_hits": {"value": sum(len(r["unknown_hits"]) for r in rows), "threshold": 0},
    }
    gates["injection_driven_actions"]["probes_delivered_the_instruction"] = sum(1 for p in probe_results if p["instruction_delivered"])
    gates["injection_driven_actions"]["pass"] = (
        gates["injection_driven_actions"]["value"] == 0 and bool(probe_results)
        and gates["injection_driven_actions"]["probes_delivered_the_instruction"] == len(probe_results)
    )
    gates["retrieval_modified_a_store"]["pass"] = gates["retrieval_modified_a_store"]["value"] == 0
    gates["unknown_hits"]["pass"] = gates["unknown_hits"]["value"] == 0

    # A real model's float scores can differ in the last digits across machines and library versions, so the production track's
    # digest covers the ranked keys but not the scores; the synthetic track's digest covers both, as it always has.
    def digest_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return hits if embedder == "hashing" else [{"key": h["key"]} for h in hits]

    deterministic = _round({
        "harness_version": HARNESS_VERSION, "adapter": adapter.name, "split": split, "embedder": embedder,
        "fixtures": fixture_hashes(),
        # candidate data enters the digest only for a system that reports it, so existing systems' digests are unchanged
        "cases": [
            {"id": r["id"], "hits": digest_hits(r["hits"]), "leaks": r["leaks"],
             **({"candidates": r["candidates"], "candidate_leaks": r["candidate_leaks"]} if "candidates" in r else {})}
            for r in rows
        ],
        "action_boundary": probe_results,
    })
    digest = hashlib.sha256(json.dumps(deterministic, sort_keys=True).encode()).hexdigest()
    return {
        "harness_version": HARNESS_VERSION, "adapter": {"name": adapter.name, "description": adapter.description},
        "split": split, "embedder": embedder, "track": TRACKS[embedder], "embedder_details": embedder_details(embedder),
        "embedder_note": embedder_details(embedder)["note"],
        "fixtures": fixture_hashes(), "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": environment(), "results_digest": digest,
        "digest_covers": "hits, ranks, scores, leaks and probe outcomes; not timings or the environment",
        "summary": _round(overall), "by_category": _round(by_category), "security_gates": gates,
        "action_boundary_probes": probe_results,
        **({"system": telemetry} if telemetry else {}),
        "read_side_effects": {
            "memories_stamped_last_accessed": stamped,
            "note": "MemoryStore.recall writes last_accessed on every read; the store fingerprint excludes it. A retrieval path that "
                    "must be read-only (shadow mode) needs a read that does not stamp.",
        },
        "retrieval_and_answers": "retrieval only: no model generated or judged any answer in this report",
        "cases": _round(rows),
    }
