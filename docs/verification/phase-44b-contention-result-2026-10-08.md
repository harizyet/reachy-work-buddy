# Phase 44B indexing contention test: result, 2026-10-08

Executed under owner decision D14 after the [plan](phase-44b-contention-test-plan-2026-10-08.md), 13:34 to 13:39 SGT, tool commit `310f0b8`. Raw report: [phase-44b-contention-2026-10-08.json](phase-44b-contention-2026-10-08.json). **No abort fired; every phase ran to its end.** Production was not written to.

## Set-up

Chat: streamed requests to the production vLLM (`reachy-local`, Qwen2.5-7B-AWQ, 64 tokens), one in flight. Speech: faster-whisper `small.en` int8 on host CPU, 4 threads (the hub's configured `STT_MODEL`), a 7.4 s synthetic clip transcribed back to back (heavier than real use, where speech is bursty). Indexing: the real `IndexingWorker` with real MiniLM, 2 torch threads, nice 10, over a synthetic 2,000-row corpus in a scratch database on a disposable Postgres container (`--cpus 2 --memory 2g`, loopback port). Phases of 90 s: A foreground, B foreground plus indexing, C indexing alone, then a 20 s foreground-only recovery check (R). Stop conditions in force: 2 consecutive failures or 3 errors of a kind or more than 5% errors after 10 attempts, chat or speech p95 above 3x baseline three checks running, a production health endpoint (hub, core, vLLM, every 5 s) failing or slower than 3 s twice, load above 14, available memory below 3 GB, stop file, 720 s cap.

## Preconditions (before start, 13:33)

No alarm or reminder due within 45 minutes; the one meeting `complete`; model manager `ready_t1`, no transition, no deep-review job; robot offline with no voice session; hub, core and vLLM healthy; production `KNOWLEDGE_INDEXING_ENABLED=false`, `knowledge_items` 0, outbox 1 row.

## Measured contention

| | A: foreground only | B: + indexing | change | R: after (recovery) |
|---|---|---|---|---|
| Chat latency p50 / p95 | 1.51 / 1.62 s | 1.66 / 1.77 s | +10% / +9% | 1.50 / 1.59 s (-1% / -2%) |
| Chat TTFT p50 / p95 | 38 / 141 ms | 37 / 60 ms | no change | 49 / 175 ms |
| Chat tokens per second | 40.8 | 37.9 | -7% | 42.0 |
| Whisper latency p50 / p95 | 1.25 / 1.33 s | 1.34 / 1.70 s | +7% / +28% | 1.25 / 1.42 s (0% / +7%) |
| Errors (chat, speech) | 0, 0 | 0, 0 | none | 0, 0 |
| Requests (chat / speech) | 72 / 73 | 67 / 66 | | 17 / 17 |

Indexing: 30.6 items/s beside the foreground work, 71.5 items/s alone (so the foreground work costs the indexer about 57% of its speed). Queue progress: in B the pending count fell from 6,270 to 3,852 and indexed rows rose 170 to 2,588; in C pending fell 3,361 to 34 (indexed 3,079 to 8,840). The worker re-queued the corpus as it drained, so item counts exceed the 2,000 rows.

Resources (means, max): host CPU 31% in A, 38% in B (max 47%), 14% in C; this process 4.8 cores in A, 6.1 in B (max 7.0), 1.6 alone for the indexer; load average 5.1 in A, 6.0 in B (max 6.8); available memory never below 6.8 GB (min 6.76 in B); process RSS 1.2 GB (MiniLM and Whisper both loaded) with about 71 to 74 threads (pools of torch and CTranslate2); event-loop lag mean under 10 ms, max about 130 ms in A and B. The scratch Postgres container idled at 0.06% CPU and 100 MB at the end.

Production health during all phases: 71 checks of hub, core and vLLM, 0 failures, slowest 31 ms.

## Post-test

The tool exited; the scratch database was dropped (`scratch_database_dropped: true`, 0 `contention_*` databases) and the Postgres container removed; the stop file never existed; load fell to 3.3 and memory stayed at 7 GB available; no error or traceback lines in core or hub logs for 15 minutes. Production after: revision `027_knowledge_index`, flag `false`, `knowledge_items` 0, `knowledge_outbox` byte-identical to before (checksum), all containers up.

## Conclusions and limits

1. **Recovery:** the assistant returned to baseline within noise (chat -1% p50, speech +0% p50, +7% p95 on 17 samples).
2. **Impact while indexing:** moderate and bounded for this synthetic worst case: chat +10%, speech p95 +28%, no errors, no health degradation. Speech was transcribing continuously, which real use does not.
3. **Extra restrictions:** none required at 2 embed threads and nice 10 on this 20-CPU host. Keep `KNOWLEDGE_EMBED_THREADS=2`. If the owner wants speech p95 protected during conversation, the cheaper lever is pausing the worker while a voice session is open (a code change, not tested or proposed for now), rather than fewer threads. Memory is not a constraint here.
4. **Limits of this measurement:** chat and Whisper clients, MiniLM and the worker shared one Python process (event-loop lag stayed small, but client-side GIL effects cannot be fully excluded); vLLM runs on the GPU, so chat contention here is mostly CPU-side overhead; the indexer ran against a synthetic corpus, not owner data; the production hub's speech path and the real Telegram or robot paths were not driven. This is a measurement for the go/no-go on enabling indexing, which remains off and unapproved.
