#!/usr/bin/env bash
# Phase 32A.V: score the speakers of ONE meeting recording against the owner's voice template, on the homelab host, keeping scores only.
# Run it yourself (it reads the owner's recording and evaluation clips); it prints only counts and writes a scores-only file.
#   bash tools/voice_identity_meeting_negatives.sh MEETING_ID [OUT_FILE]
# Needs the hub and core image tags, the Compose network, the owner-recognition and meeting-audio volumes and the key file.
# It reads, never writes, those volumes, and removes its temporary directory on exit.
set -euo pipefail
MEETING="${1:?usage: voice_identity_meeting_negatives.sh MEETING_ID [OUT_FILE]}"
OUT="${2:-$HOME/reachy-backups/phase32a-deploy/meeting-scores.json}"
HUB_IMAGE="${HUB_IMAGE:-reachy-homelab-reachy-hub:p32a-aa3e38b}"
CORE_IMAGE="${CORE_IMAGE:-reachy-homelab-companion-core:p32a-aa3e38b}"
NET="${NET:-reachy-homelab_default}"
KEY="${KEY:-/home/hariz/reachy-work-buddy/deploy/homelab/.env.secret-keys.json}"
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
chmod 700 "$T"
trap 'rm -rf "$T"' EXIT

# 1. the owner's template, rebuilt from the evaluation enrolment clips (the same recipe as tools/voice_identity_benchmark.py)
cat > "$T/template.py" <<'PY'
import asyncio, json, sys, httpx
sys.path.insert(0, "/tools")
import voice_identity_benchmark as t
from reachy_hub.enrollment_store import FilesystemEnrollmentStore
from reachy_hub.keyring import Keyring
from reachy_hub.voice_identity import centroid
from shared.models.enrollment import EnrollmentSampleKind
store = FilesystemEnrollmentStore("/data/owner-recognition-captures", Keyring.from_file("/run/secrets/credential_keys"))
async def go():
    vecs, http = [], httpx.Client(timeout=60)
    for s in await store.list_samples(EnrollmentSampleKind.VOICE):
        lab = t.parse_label(s.label)
        if lab and lab["role"] == "enroll" and lab["speaker"] == "owner":
            r = http.post("http://speaker:8012/embed", files={"file": ("a.wav", await store.read_sample(EnrollmentSampleKind.VOICE, s.sample_id), "audio/wav")})
            if r.status_code == 200 and r.json()["speech_s"] >= 1.5:
                vecs.append(r.json()["embedding"])
    json.dump({"template": centroid(vecs), "n": len(vecs)}, open("/work/template.json", "w"))
    print("template from", len(vecs), "clips")
asyncio.run(go())
PY
docker run --rm --network "$NET" -e PYTHONPATH=/app/services/reachy-hub/src:/app \
  -v reachy-homelab_owner-recognition-captures:/data/owner-recognition-captures:ro -v "$KEY":/run/secrets/credential_keys:ro \
  -v "$HERE":/tools:ro -v "$T":/work --entrypoint /app/.venv/bin/python "$HUB_IMAGE" /work/template.py

# 2. who spoke when: anonymous labels and times only (no names, no text)
docker exec reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -Atc \
  "select coalesce(jsonb_agg(jsonb_build_object('speaker', s->>'speaker', 'start', (s->>'start')::float, 'end', (s->>'end')::float)), '[]') from meetings m, jsonb_array_elements(m.diarization_segments) s where m.id='$MEETING'" > "$T/segments.json"

# 3. windows from the recording, scored against the template; only scores come out
docker run --rm --network "$NET" -e MEETING_ID="$MEETING" -v reachy-homelab_meeting-audio:/data/meeting-audio:ro \
  -v "$HERE/voice_identity_meeting_negatives.py":/stage2.py:ro -v "$T":/work --entrypoint /app/.venv/bin/python "$CORE_IMAGE" /stage2.py
mkdir -p "$(dirname "$OUT")"
cp "$T/scores.json" "$OUT"
chmod 600 "$OUT"
echo "scores written to $OUT (scores only; temporary files removed)"
