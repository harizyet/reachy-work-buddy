# Jarvis Reference Baseline (Phase 1)

- Status: Documented from static source analysis, not a live run.
- Source: [haasonsaas/jarvis](https://github.com/haasonsaas/jarvis), cloned at commit
  `355a67924029b60d01f7e423e68ff9d20b70aefe` into `vendor/jarvis` (gitignored —
  reference only, not part of our services; see "Why not vendored" below).

## Why this baseline is static, not a live run

Jarvis's live voice loop (`uv run python -m jarvis --sim --no-vision`) requires
`OPENAI_API_KEY` and `ELEVENLABS_API_KEY`, and its full hardware loop requires a
physical Reachy Mini. Neither was available in the environment this baseline was
written in. This document instead records the **known-good reference behaviour
as designed and implemented**, extracted from source, docstrings, and the
project's own architecture diagram, to the level of detail Phase 2/3 need to
adapt `reachy-embodiment` from it. When real API keys and/or hardware are
available, re-run `make test-sim`, `make test-faults`, and a live
`--sim --no-vision` session and fold observed deltas into this doc.

## Why not vendored into the repo

`vendor/jarvis` is a full clone (~5.3MB, 250+ source files, its own `uv.lock`)
kept locally for reference during adaptation. It is **not** committed — it's
listed in `.gitignore`. We are not forking Jarvis (see ADR-backed decision in
`docs/plan.md` §3: "Jarvis should accelerate the project but should not
determine the long-term architecture"). Code we actually reuse gets copied and
adapted into `services/reachy-embodiment` under our own boundaries (ADR 0001),
not imported from a vendored tree.

## Architecture as implemented

Jarvis's own diagram (`vendor/jarvis/README.md`):

```
┌───────────────────────────────────────────────────────────────────┐
│                      PRESENCE LOOP (30Hz)                          │
│  Always running. Receives lightweight signals, outputs motion.     │
│                                                                      │
│  Signals in:              States:                                  │
│    vad_energy ──┐          IDLE     → breathing, drift              │
│    doa_angle  ──┤          LISTENING → orient, micro-nods, lean     │
│    face_pos   ──┼────────► THINKING → look away, processing anim   │
│    llm_state  ──┤          SPEAKING → stable gaze, intent motion   │
│    embody_cmd ──┘          MUTED    → privacy posture               │
└───────────────────────────────────────────────────────────────────┘

┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Audio Input    │     │   Agent Brain     │     │   Audio Output   │
│  Mic → VAD ──────┼────►│  Agent SDK       │────►│  Stream TTS      │
│       ↓          │     │  + MCP tools     │     │  (ElevenLabs)    │
│  Whisper STT ────┼────►│                  │     │  Barge-in:       │
│  Barge-in: ◄─────┼─────│                  │◄────│  VAD interrupts  │
│  stop TTS        │     │                  │     │  playback        │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

This maps directly onto our own boundary split (ADR 0001): Jarvis's "Agent
Brain" is our `companion-core`; its "Presence Loop" + "Audio Input/Output" +
robot control is our `reachy-embodiment`; it has no equivalent of our
`reachy-hub` (multi-channel session/transport) — Jarvis is single-channel,
voice-only, one continuous process. That gap is exactly what Phases 4-7
(control plane, sessions, Telegram) add that Jarvis does not have.

## Module-by-module baseline (relevant to our reuse decisions)

### `audio/vad.py` (95 lines) — Silero VAD

- Wraps the `silero-vad` pip package's `VADIterator` for streaming
  end-of-utterance and barge-in detection.
- **Hard constraint**: 16kHz audio, fixed 512-sample (32ms) chunks — this is a
  Silero model requirement, not configurable.
- `torch.set_num_threads(1)` — deliberately single-threaded; the model is
  small enough that thread overhead costs more than it saves.
- Confirms ADR reuse decision ("Reuse/adapt" — Silero VAD and barge-in are
  already solved) is accurate: this module is small, self-contained, and has
  no coupling to Jarvis's brain/tools layers. Safe to adapt directly into
  `reachy-embodiment`'s audio pipeline.

### `audio/stt.py` (165 lines) — faster-whisper

- `SpeechToText` wraps `faster_whisper.WhisperModel`, default `base.en`,
  `compute_type="int8"` (CPU-friendly).
- Includes confidence scoring/tokenization helpers (`_tokenize_words`,
  `_clamp01`) used elsewhere for STT confidence diagnostics
  (`voice_attention.stt_diagnostics` per the Jarvis README) — a feature
  beyond our current scope but worth keeping in mind for Phase 8.
- Self-contained aside from `jarvis.audio.runtime_audio.resample_audio`.
  Reuse into `reachy-embodiment` should bring that resample helper along or
  reimplement it (it's a small utility).

### `audio/tts.py` (98 lines) — ElevenLabs streaming

- Uses `stream()` (not `convert()`) against ElevenLabs specifically for low
  time-to-first-byte; targets `eleven_flash_v2_5` (~75ms TTFB).
- Outputs raw PCM int16 at 16kHz — no codec overhead.
- Tracks `_prev_request_ids` for cross-utterance prosody continuity.
- Confirms ADR decision ("Retain streaming interface but make provider
  pluggable"): the streaming *interface* (`stream_chunks` yielding
  progressive audio) is the reusable shape; the ElevenLabs-specific client
  call is the part to abstract behind a provider interface per docs §8
  ("TTS: Cloud initially... later local option").

### `presence.py` (520 lines) — the presence loop

- Runs at a fixed `LOOP_HZ = 30` independent thread (`PresenceLoop.start()` /
  `.stop()`, `_loop()` running on its own `threading.Thread`).
- `State` enum: `IDLE, LISTENING, THINKING, SPEAKING, MUTED` — five states,
  not the seven in our `EmbodimentState` (ADR 0004 adds `REMOTE`,
  `DISCONNECTED`, `SLEEP` on top of Jarvis's `MUTED`/lack of connectivity
  awareness — Jarvis has no concept of "homelab unreachable" because it has
  no homelab; everything is one process).
- `Signals` dataclass is the **entire interface** between the brain/audio/
  vision threads and the presence loop: `doa_angle`, `vad_energy`,
  `face_yaw/pitch/detected`, `intent_nod/bow/tilt/glance_yaw` (set by the
  LLM's embodiment plan), `turn_lean/tilt/glance_yaw` (turn-taking
  choreography), `speech_energy` (drives speech sway), `hand_*`. Comment in
  source: "Individual float/bool writes are atomic on CPython (GIL), so we
  don't need locks" — a real constraint of the design, not a bug.
- Per-state behaviour methods (`_do_idle`, `_do_listening`, `_do_thinking`,
  `_do_speaking`, `_do_muted`) are small, readable, and directly analogous
  to what `reachy-embodiment`'s behaviour catalogue needs to implement per
  ADR 0003. This is the strongest single candidate for direct adaptation.
- **Critically for ADR 0001**: "The LLM never touches this loop directly. It
  just sets signals." This is precisely our cognition/embodiment boundary,
  already proven out by Jarvis at the presence-loop level — validates that
  boundary is a comparably-shaped than the previous approach designed.

### `robot/controller.py` (474 lines) — Reachy Mini SDK wrapper

- `RobotController` wraps `reachy_mini.ReachyMini` with a small stateful API:
  `connect`/`disconnect`, `move_head`/`set_head_realtime` (via `HeadPose`
  dataclass: x/y/z mm + roll/pitch/yaw degrees), `turn_body`, `set_antennas`,
  `run_sequence`/`run_macro`, `play_emotion`/`play_dance` (loading from
  `pollen-robotics/reachy-mini-emotions-library` and
  `-dances-library` HF datasets — confirms plan §5's recorded-move claim),
  plus low-level audio (`start_audio`, `get_audio_sample`,
  `push_audio_sample`) and `get_doa()` (direction-of-arrival for the mic
  array).
- `HEAD_LIMITS` dict enforces conservative safety clamps (`_clamp_pose`) in
  degrees/mm before any motion command reaches hardware — a real safety
  mechanism worth reusing in `reachy-embodiment`, not just a nice-to-have.
- `sim` and `connected` properties confirm the SDK itself supports a
  simulation/no-hardware mode at this layer (not just at the Jarvis app
  layer via `--sim`).
- Confirms ADR 0003's "Adapt" decision: this file directly couples motion
  primitives to the conversation/brain layer's needs (e.g. macros named for
  conversational intents). `reachy-embodiment` should wrap the same
  `ReachyMini` SDK surface but expose it only through the semantic
  `EmbodimentCommand`/behaviour-name API, never re-exposing `move_head`/
  `HeadPose` directly to `companion-core`.

### `memory.py` (2163 lines) — memory + governance

- `MemoryStore` (SQLite-backed) plus `MemoryEntry`, `TaskStep`/`TaskPlan`,
  `TimerEntry`, `ReminderEntry`, `MemorySummary` dataclasses.
- Optional Fernet encryption (`cryptography` package, soft-imported) and
  optional OpenAI-embeddings-backed search (soft-imported) — both feature
  flagged, not hard dependencies.
- Confirms "Reuse concepts" is the right call, not "reuse code": this file
  is 2163 lines and deeply coupled to Jarvis's own tool-calling surface
  (`services.py` and friends). Our `MemoryRecord` (ADR-driven,
  `shared/models/memory.py`) already extracts the useful concepts
  (provenance via `source`, `sensitivity`, `expires_at`) without the
  SQLite/encryption/embedding implementation coupling. Phase 12 should
  design `companion-core`'s memory store fresh against `MemoryRecord`,
  consulting this file for the provenance/staleness ideas only.

### `tools/services_*_runtime.py` — audit/trust/policy (governance)

- Split into narrow single-purpose modules:
  `services_policy_engine_runtime.py` (`default_policy_engine()` — data-driven
  policy: `high_risk_domains`, `require_confirm_domains`, etc.),
  `services_audit_*_runtime.py` (crypto, event, facade, retention, sanitize —
  audit log encoding/redaction/retention split cleanly),
  `services_identity_runtime.py` (trust scoring, HMAC-based identity checks).
- This confirms the plan's permission-tier model (docs §9: Observe / Prepare
  / Act / Control) is compatible with Jarvis's own design
  (`high_risk_domains`/`require_confirm_domains` + `confirm=true` gating +
  audit-every-decision), and that "Reuse concepts" here means: reuse the
  *shape* (data-driven policy table + audit event with decision/reason/
  explanation fields), not this specific module split, which is entangled
  with Jarvis's 60+ `services_*_runtime.py` tool-calling framework that we
  are not adopting (`brain/conversation loop` is "Reference only" per ADR
  0001 rationale).

## What this baseline does *not* establish

Because no live run was performed, this document does not verify:

- Actual first-audible-response latency (README claims 300-600ms).
- Real barge-in behaviour under live audio.
- Face tracking accuracy or the YOLOv8 vision pipeline (out of scope for our
  V0.1 anyway — no vision requirement in docs plan §7).
- Whether `make test-sim` / `make test-faults` pass in this environment
  (not run — would need `uv sync` inside `vendor/jarvis` and its own
  dependency set, which is large and includes `torch`, `faster-whisper`,
  `ultralytics`, etc.).

## Phase 1 exit criterion

Per docs/plan.md §6: "Known-good reference behaviour is documented." — met
for the modules relevant to Phases 2-3 (`vad.py`, `stt.py`, `tts.py`,
`presence.py`, `robot/controller.py`) via static analysis above. Live
validation (`make test-sim`, a real `--sim --no-vision` run) remains a
follow-up once API keys are available — tracked as an open item, not a
blocker for Phase 2, since Phase 2 builds our own `reachy-embodiment` HTTP
skeleton rather than running Jarvis itself.
