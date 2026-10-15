"""Phase 32A.V gate GV: owner-verification evaluation against the real speaker service.

Input is the labelled voice dataset the Android app's "Voice evaluation" screen uploads to the hub's benchmark store
(docs/verification/phase-32a-gv-protocol.md), either as the export zip or fetched directly, or a JSON-lines manifest of local WAVs.
Each clip embeds through the `speaker` service; the owner is enrolled from the `enroll` clips exactly as the hub does (same
`centroid`/`cosine`); every `trial` clip is scored. Trials are three kinds:

  genuine   the owner speaking live (conditions such as quiet, noisy, held_out)
  impostor  a consenting non-owner speaking live
  attack    a presentation attack: condition `replay` (the owner's recorded voice played through another speaker) or
            `synthetic` (text-to-speech or converted speech), whoever the speaker label names

The report gives per-condition counts, FAR (impostors accepted) and attack acceptance with Wilson 95% intervals, FRR, a
threshold sweep and *threshold candidates with their observed error rates*. It does NOT choose a threshold: that is the owner's
decision after reading it. It keeps nothing but the report on stdout.

    python tools/voice_identity_benchmark.py --export voice-benchmark-dataset.zip --url http://localhost:8012 > report.json
    REACHY_PASSWORD=... python tools/voice_identity_benchmark.py --fetch http://hub:8080/hub --username owner --url ...
    python tools/voice_identity_benchmark.py manifest.jsonl --owner owner --url ...    # {"path","speaker","role","condition"}
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import statistics
import sys
import time
import zipfile
from collections import defaultdict
from pathlib import Path

SWEEP_STEPS = 49
ATTACK_CONDITIONS = {"replay", "synthetic"}
MIN_ENROLL_CLIPS = 5
MIN_ENROLL_SPEECH_S = 1.5


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson interval for a rate; None when there are no trials. Small private test sets give wide intervals: report them."""
    if total == 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return round(max(centre - half, 0.0), 4), round(min(centre + half, 1.0), 4)


def rate(successes: int, total: int) -> dict:
    return {"count": successes, "of": total, "rate": round(successes / total, 4) if total else None, "ci95": wilson(successes, total)}


def classify(score: float, accept: float, uncertain: float) -> str:
    return "verified" if score >= accept else "uncertain" if score >= uncertain else "not_verified"


def trial_kind(speaker: str, owner: str, condition: str) -> str:
    """Attacks are attacks whoever they claim to be: a replayed owner clip must be rejected like an impostor."""
    if condition in ATTACK_CONDITIONS:
        return "attack"
    return "genuine" if speaker == owner else "impostor"


def summarize(trials: list[dict], accept: float, uncertain: float) -> dict:
    """trials: {"kind": genuine|impostor|attack, "score": float, "condition": str}. FAR = impostor trials called verified; attack
    acceptance = attack trials called verified; FRR = genuine trials not called verified (uncertain counts against access but is
    also shown in the matrix)."""
    def block(rows: list[dict]) -> dict:
        matrix = {kind: {state: 0 for state in ("verified", "uncertain", "not_verified")} for kind in ("genuine", "impostor", "attack")}
        for r in rows:
            matrix[r["kind"]][classify(r["score"], accept, uncertain)] += 1
        n = {kind: sum(matrix[kind].values()) for kind in matrix}
        return {
            "trials": n, "matrix": matrix,
            "far": rate(matrix["impostor"]["verified"], n["impostor"]),
            "attack_acceptance": rate(matrix["attack"]["verified"], n["attack"]),
            "frr": rate(n["genuine"] - matrix["genuine"]["verified"], n["genuine"]),
        }

    by_condition: dict[str, list[dict]] = defaultdict(list)
    for t in trials:
        by_condition[t["condition"]].append(t)
    return {"overall": block(trials), "by_condition": {c: block(rows) for c, rows in sorted(by_condition.items())}}


def _scores(trials: list[dict], *kinds: str) -> list[float]:
    return [t["score"] for t in trials if t["kind"] in kinds]


def sweep(trials: list[dict], steps: int = SWEEP_STEPS) -> list[dict]:
    genuine, impostor, attack = _scores(trials, "genuine"), _scores(trials, "impostor"), _scores(trials, "attack")
    out = []
    for i in range(steps):
        threshold = -0.2 + i * (1.2 / (steps - 1))
        out.append({
            "threshold": round(threshold, 3),
            "far": round(sum(s >= threshold for s in impostor) / len(impostor), 4) if impostor else None,
            "attack_acceptance": round(sum(s >= threshold for s in attack) / len(attack), 4) if attack else None,
            "frr": round(sum(s < threshold for s in genuine) / len(genuine), 4) if genuine else None,
        })
    return out


def candidates(trials: list[dict]) -> list[dict]:
    """Threshold candidates with the error rates *observed on this dataset*. Candidates, not recommendations: a threshold chosen
    on the data that also measures it is optimistic, and with few trials the intervals are wide."""
    genuine, impostor, attack = _scores(trials, "genuine"), _scores(trials, "impostor"), _scores(trials, "attack")
    negatives = sorted(impostor + attack)
    if not genuine or not negatives:
        return []

    def at(name: str, threshold: float, why: str) -> dict:
        return {
            "name": name, "threshold": math.ceil(threshold * 10000) / 10000, "why": why,  # rounded up: never down onto a score that was rejected
            "far": rate(sum(s >= threshold for s in impostor), len(impostor)),
            "attack_acceptance": rate(sum(s >= threshold for s in attack), len(attack)),
            "frr": rate(sum(s < threshold for s in genuine), len(genuine)),
        }

    pool = sorted(set(genuine + negatives))
    eer = min(pool, key=lambda t: abs(sum(s >= t for s in negatives) / len(negatives) - sum(s < t for s in genuine) / len(genuine)))
    one_false = negatives[-2] + 1e-6 if len(negatives) > 1 else negatives[-1] + 1e-6
    return [
        at("no_observed_false_accept", negatives[-1] + 1e-6, "just above the highest impostor/attack score seen: zero false accepts here, which is not zero in general"),
        at("at_most_one_observed_false_accept", one_false, "tolerates the single highest impostor/attack score"),
        at("equal_error_point", eer, "false accepts and false rejects balanced on this data"),
    ]


def percentiles(values: list[float]) -> dict:
    if not values:
        return {}
    ordered = sorted(values)
    pick = lambda q: ordered[min(len(ordered) - 1, int(q * len(ordered)))]
    return {"n": len(values), "p50": round(statistics.median(values), 3), "p95": round(pick(0.95), 3), "max": round(ordered[-1], 3)}


def parse_label(label: str | None) -> dict | None:
    if not label:
        return None
    parts = dict(item.split("=", 1) for item in label.split(";") if "=" in item)
    return parts if {"role", "speaker", "condition"} <= set(parts) else None


def entries_from_export(archive: bytes) -> tuple[list[dict], int]:
    """(entries with audio bytes, number of unlabelled clips skipped) from the hub's benchmark export zip."""
    entries, skipped = [], 0
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for item in json.loads(zf.read("manifest.json")):
            label = parse_label(item.get("label"))
            if label is None:
                skipped += 1
                continue
            name = f"{item['sample_id']}.{item['content_type'].split('/')[-1]}"
            entries.append({**label, "name": item["sample_id"], "data": zf.read(name)})
    return entries, skipped


def fetch_export(hub: str, username: str, password: str) -> bytes:
    import httpx

    headers = {"X-Reachy-CSRF": "1"}
    with httpx.Client(base_url=hub.rstrip("/"), timeout=60) as http:
        http.post("/auth/login", json={"username": username, "password": password}, headers=headers).raise_for_status()
        http.post("/owner-recognition/reauth", json={"password": password}, headers=headers).raise_for_status()
        response = http.get("/owner-recognition/benchmark/voice/export", headers=headers)
        response.raise_for_status()
        return response.content


def evaluate(entries: list[dict], owner: str, embed, accept: float | None, uncertain: float | None) -> tuple[dict, int]:
    """entries: {"name","data","speaker","role","condition"}; embed(bytes) -> {"embedding","model_version","speech_s","process_s"} or None."""
    from reachy_hub.voice_identity import centroid, cosine

    embedded, wall, service = [], [], []
    for entry in entries:
        t = time.perf_counter()
        body = embed(entry["data"])
        wall.append(time.perf_counter() - t)
        if body is None:
            print(f"skipped {entry['name']}: not embeddable", file=sys.stderr)
            continue
        service.append(body["process_s"])
        embedded.append({**entry, "vector": body["embedding"], "model_version": body["model_version"], "speech_s": body["speech_s"]})
    enroll = [e["vector"] for e in embedded if e["role"] == "enroll" and e["speaker"] == owner and e["speech_s"] >= MIN_ENROLL_SPEECH_S]
    if len(enroll) < MIN_ENROLL_CLIPS:
        print(f"need at least {MIN_ENROLL_CLIPS} usable owner enrollment clips, found {len(enroll)}", file=sys.stderr)
        return {}, 2
    template = centroid(enroll)
    trials = [{"kind": trial_kind(e["speaker"], owner, e["condition"]), "score": cosine(e["vector"], template), "condition": e["condition"]}
              for e in embedded if e["role"] == "trial"]
    report = {
        "model_version": sorted({e["model_version"] for e in embedded}), "enrollment_clips": len(enroll),
        "trials": {kind: sum(t["kind"] == kind for t in trials) for kind in ("genuine", "impostor", "attack")},
        "speakers": sorted({e["speaker"] for e in embedded}),
        "threshold_candidates": candidates(trials), "sweep": sweep(trials),
        "latency_s": {"http_round_trip": percentiles(wall), "service_embedding": percentiles(service)},
        "limits": "Small private set: read the intervals, not the point rates. Candidates are observed on the same data that measures them. "
                  "Replay and synthetic rows measure only what was tried; this is not a spoof-immunity claim. No threshold has been selected.",
    }
    if accept is not None and uncertain is not None:
        report["thresholds_applied"] = {"accept": accept, "uncertain": uncertain}
        report.update(summarize(trials, accept, uncertain))
    return report, 0


def main(argv: list[str] | None = None) -> int:
    import httpx

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("manifest", nargs="?", help="JSON-lines manifest of local WAVs (alternative to --export/--fetch)")
    parser.add_argument("--export", help="the hub's voice benchmark export zip")
    parser.add_argument("--fetch", help="hub base URL: log in, re-authenticate and download the export (password from REACHY_PASSWORD)")
    parser.add_argument("--username", default="owner")
    parser.add_argument("--owner", default="owner", help="the speaker label that is the owner")
    parser.add_argument("--url", default="http://localhost:8012", help="speaker service base URL")
    parser.add_argument("--token", default=os.environ.get("SPEECH_SERVICE_TOKEN"))
    parser.add_argument("--accept", type=float, help="optional: also tabulate the confusion matrix at this accept threshold")
    parser.add_argument("--uncertain", type=float, help="optional: lower (inconclusive) threshold; with --accept")
    args = parser.parse_args(argv)
    if (args.accept is None) != (args.uncertain is None) or (args.accept is not None and args.uncertain > args.accept):
        parser.error("give both --accept and --uncertain, with --uncertain <= --accept, or neither")

    if args.fetch:
        password = os.environ.get("REACHY_PASSWORD")
        if not password:
            parser.error("set REACHY_PASSWORD in the environment (never on the command line)")
        entries, skipped = entries_from_export(fetch_export(args.fetch, args.username, password))
    elif args.export:
        entries, skipped = entries_from_export(Path(args.export).read_bytes())
    elif args.manifest:
        lines = [json.loads(line) for line in Path(args.manifest).read_text().splitlines() if line.strip()]
        entries, skipped = [{**e, "name": e["path"], "data": Path(e["path"]).read_bytes()} for e in lines], 0
    else:
        parser.error("give a manifest, --export or --fetch")
    if skipped:
        print(f"{skipped} unlabelled clip(s) ignored", file=sys.stderr)

    headers = {"X-Reachy-Speech-Token": args.token} if args.token else {}
    with httpx.Client(timeout=60) as http:
        def embed(data: bytes):
            response = http.post(args.url.rstrip("/") + "/embed", files={"file": ("a.wav", data, "audio/wav")}, headers=headers)
            return response.json() if response.status_code == 200 else None

        report, code = evaluate(entries, args.owner, embed, args.accept, args.uncertain)
    if code:
        return code
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
