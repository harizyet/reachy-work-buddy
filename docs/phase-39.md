# Phase 39: Persona-aware responses and authoritative action receipts

Status: **started 2026-10-06.** Scope and exit criterion are owned by the [forward roadmap](plan.md#forward-roadmap-phases-30); this page owns
the stage sequence and gates. The decision is [ADR 0028](adr/0028-persona-responses-and-action-receipts.md).

Invariant: the LLM may describe system truth; it may not define it.

## Stages

| Stage | Work | State | Gate to the next stage |
|---|---|---|---|
| 39.0 Documents | Roadmap row, this page, ADR 0028 | **Done 2026-10-06** | Owner can redirect scope |
| 39.1 Receipt model and store | `ActionReceipt`, migration 018, `PlannerStore` add/list/claim (InMemory and Postgres), core `GET /receipts`, `GET /receipts/pending` | **Done 2026-10-06** (Postgres durability test passes against a disposable pgvector container) | Store parity and claim-once tested |
| 39.2 Template renderer | `companion_core/persona/render.py`, default tone equals the previous strings, every tone covers every event | **Done 2026-10-06** (`test_receipts.py`) | Per-tone and default-parity tests |
| 39.3 LLM verbalizer | Optional small-model rewrite of a structured result with deterministic fallback | **Not started**; deferred until templates prove insufficient | n/a |
| 39.4 Handlers record receipts | Alarm (offer, phrase, REST create, cancel, delivery), task capture/complete, reminder, memory | **Done 2026-10-06** | Receipts match persisted objects; failed lookups record none |
| 39.5 Telegram receipts | Hub `receipt_notify_loop` claims and pushes once | **Done 2026-10-06** (`test_alarm_loop.py`, simulated Telegram) | Pushed once; Telegram-origin turns not echoed |
| 39.6 Operator UI | Activity tab, hub `GET /planner/receipts` proxy | **Done 2026-10-06** (`activity.test.cjs`) | Literal rendering at the direct mount |
| 39.7 Coding/calendar/briefing replies | Persona rendering for read-only replies | **Not started** | n/a |
| 39.8 Fixed-reply audit | Classify every remaining fixed reply as class A/B/C | **Not started** | n/a |
| 39.9 Acceptance | Deploy with backup (migration 018), live Telegram receipt and tone check with the owner | **Pending** | Owner |

## Deviations from the proposal

- Telegram receipts skip slash commands and Telegram-origin turns (the reply is already in that chat).
- No `ResponseEnvelope` yet; class B uses templates only (39.3 deferred).
- No receipt retention or observability counters yet.
