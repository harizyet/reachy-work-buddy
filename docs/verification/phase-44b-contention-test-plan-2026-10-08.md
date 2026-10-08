# Phase 44B indexing contention test: plan for go/no-go (prepared 2026-10-08, not run)

Owner decision D14. **Nothing here has been executed against production or the live robot.** The tool is
[tools/knowledge_contention_test.py](../../tools/knowledge_contention_test.py); it is to be run only after migration 027
has passed production acceptance, and only on a separate owner go/no-go.

## Question

Does building the knowledge index (the real `IndexingWorker` with the real MiniLM embedder) slow down speech-to-text and
chat enough to matter on the production host?

## Design

Three phases of equal length (default 90 s): **A** foreground only, **B** foreground plus indexing, **C** indexing only.

| Workload | What runs | Where |
|---|---|---|
| Chat | one request in flight at a time, OpenAI-compatible POSTs, `max_tokens` 64 | the local vLLM (`--chat-url`) |
| Speech | faster-whisper `base.en`, int8, 4 CPU threads, a short clip transcribed repeatedly (`--stt local`), or an HTTP endpoint (`--stt http`) | in the tool's process, on host CPU as the hub's STT does |
| Indexing | `IndexingWorker` + MiniLM (`embed_threads` 2) over a synthetic corpus (default 2000 rows) | a **scratch database** on a disposable Postgres server, created and dropped by the tool |

Production data and the production database are never read or written. Chat answers are generic prompts, not user content.

## Resource limits

Torch threads 2 for the worker; the process is `nice` 10; optional CPU pinning (`--cpus N`); one request in flight per
foreground workload; scratch Postgres in its own container (recommend `--cpus 2 --memory 2g`). Host: 20 CPUs, ~30 GB RAM.

## Automatic stop conditions (checked every second; any one ends all workloads, skips remaining phases, drops the scratch DB)

- host 1-minute load average above 14
- available memory below 3 GB
- chat or speech error rate above 20% (after 5 attempts)
- phase B chat p95 above 3x the phase A p95, over the last 20 requests, three checks in a row
- a stop file (`--stop-file`) appears: `touch /tmp/stop-contention` from any shell
- hard cap of 720 s total

## Expected duration

3 x 90 s = 4.5 min of load plus about 1-2 min setup (migrate scratch DB, load MiniLM and Whisper): roughly 7 min.
Run during a quiet window, with the robot not in conversation. No robot motion is involved.

## Cleanup and rollback

The tool drops the scratch database on every exit path (reported as `cleanup.scratch_database_dropped`). The owner or
Claude then removes the scratch Postgres container. Nothing in production changes, so there is no production rollback;
`KNOWLEDGE_INDEXING_ENABLED` stays false throughout.

## Proposed command (to be confirmed at go/no-go)

```
python tools/knowledge_contention_test.py --chat-url http://localhost:8003/v1/chat/completions --chat-model <served name> \
  --stt local --stt-model base.en --stt-audio <clip.wav> --index worker --scratch-admin-url <scratch server admin URL> \
  --scale 2000 --seconds 90 --embed-threads 2 --nice 10 --stop-file /tmp/stop-contention --confirm-owner-approved --out <report.json>
```

## Verification of the tool so far

Stub servers with a CPU burner (`--self-test`): passes, including the error-rate abort and stop-file paths (pytest
`test_knowledge_index.py -k contention`). The real worker against a scratch database on the 44D test Postgres (burner
instead of MiniLM, 200 rows): runs all three phases, drops the database. Not yet exercised: MiniLM, local Whisper and the real
vLLM together; that is what the run is for.
