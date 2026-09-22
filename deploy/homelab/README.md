# deploy/homelab

Docker Compose deployment for `companion-core`, `reachy-hub`, PostgreSQL
(with the pgvector extension, for Phase 13's document store), Mailpit
(Phase 14's local SMTP target), and a Caddy reverse proxy. Kubernetes is
explicitly out of scope for initial releases (see docs/plan.md §1
non-goals).

`reachy-embodiment` is also included in this compose file, purely so the
full chain (companion-core -> reachy-hub -> reachy-embodiment) can be
smoke-tested locally with one `docker compose up`. In a real deployment
reachy-embodiment runs on the Reachy Mini itself (see
[deploy/reachy](../reachy/)), not in this homelab stack.

Redis is not included — `AgentSession` state (Phase 5) fit fine in Postgres
(see `services/reachy-hub/src/reachy_hub/postgres_session_store.py`) rather
than needing a separate cache; nothing else has made a concrete case for
Redis yet.

Verified with real `docker compose up --build` runs against this exact file
(Docker Compose v2, Postgres 16, Caddy 2): all five containers start
(`reachy-embodiment` now builds with `torch`/`silero-vad`, `reachy-hub`
with `faster-whisper` and `espeak-ng`, `companion-core` now connects to
Postgres for the first time ever); the robot registry, `AgentSession`
state, audit log, and calendar data all survive container restarts
(Postgres persistence); requests routed through Caddy reach
reachy-embodiment/companion-core and change their reported state — end to
end, through the actual reverse proxy, not just localhost port-forwarding;
a `POST /hub/voice/turn` request with a real synthesized WAV question,
routed through Caddy, produced a real transcribed/routed/synthesized WAV
reply (Phase 8); a sensitive-content payload sent through Caddy in Office
mode correctly resolved to `phone`, never `reachy` (Phase 9); a real
calendar event added through Caddy produced a real "what's next" answer,
and a reminder for an imminent meeting correctly routed away from Reachy
(Phase 10); a task recorded conversationally through Caddy was retrieved
in a later turn and via the direct API (Phase 11); a work fact recorded
conversationally through Caddy ("remember that my manager's email is
alice@example.com") was recalled later, through both the conversational
path and the direct API, with the reply containing only the matching fact
and none of the other turns exchanged in between — the actual exit
criterion, not just a passing test — and it survived a `companion-core`
container restart via Postgres (Phase 12); two documents ingested through
Caddy, with a time-off question through the conversational path correctly
retrieving the Vacation Policy chunk (not the unrelated Expense Policy
one, by real semantic similarity, not keyword matching) with its section
named in the reply, and the same data surviving a `companion-core`
container restart via Postgres/pgvector (Phase 13) — getting there
surfaced two bugs no unit test caught: an uncommitted `CREATE EXTENSION`
left pool connections stuck mid-transaction, and a bare vector query
parameter needed an explicit `::vector` cast or Postgres tried to match it
against `double precision[]` instead; an email drafted conversationally
through Caddy could not be sent before approval — confirmed against
Mailpit's own message list staying empty, not just the HTTP response —
and, once approved, produced a real SMTP message that actually arrived in
Mailpit, with the draft surviving a `companion-core` restart via Postgres
and a repeat send on an already-sent draft correctly rejected (Phase 14);
and, separately (not
through this specific compose stack, but the same services run as plain
processes), a real Telegram bot and a real Telegram account confirmed
Phase 7's session continuity live.

## Run it

```
cp .env.example .env   # set a real POSTGRES_PASSWORD
docker compose up -d --build
```

```
curl http://localhost:8080/hub/health
curl http://localhost:8080/core/health

curl -X POST http://localhost:8080/hub/robots \
  -H 'Content-Type: application/json' \
  -d '{"robot_id": "desk-1", "base_url": "http://reachy-embodiment:8000"}'

curl http://localhost:8080/core/debug/robots/desk-1/state
curl -X POST http://localhost:8080/core/debug/robots/desk-1/behaviour/greeting
```

Sessions (Phase 5) — two separate `curl` calls standing in for two
different channels/clients, same user, one shared conversation:

```
curl -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "hariz", "channel": "reachy", "text": "whats on my calendar"}'

curl -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "hariz", "channel": "telegram", "text": "continue that"}'
# -> same session_id/conversation_id as the first call, active_channel now
#    "telegram", and companion-core's turn counter advanced to 2.

curl http://localhost:8080/hub/sessions/hariz
```

Operating modes (Phase 6) — same text, different mode, different resolved
`delivery_channel`, without ever changing what was sent to companion-core:

```
curl -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "hariz", "channel": "telegram", "text": "whats on my calendar"}'
# -> delivery_channel: "reachy" (Desk is the default mode)

curl -X PATCH http://localhost:8080/hub/sessions/hariz/mode \
  -H 'Content-Type: application/json' -d '{"interaction_mode": "office"}'

curl -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "hariz", "channel": "telegram", "text": "whats on my calendar"}'
# -> delivery_channel: "phone" — same text, mode alone changed the routing
```

Telegram (Phase 7) — optional, set `TELEGRAM_BOT_TOKEN` (and
`TELEGRAM_DEFAULT_USER_ID`, matching the `user_id` used above) in `.env`
before `docker compose up` to enable it. Unset, `reachy-hub` runs fine
without any Telegram code path active. With it set: message your bot on
Telegram and `curl http://localhost:8080/hub/sessions/<your user_id>` shows
`active_channel: "telegram"` with the same `session_id` as any prior
Reachy-channel message for that user — verified against a real bot and a
real Telegram account, not just curl.

Voice (Phase 8) — a real conversation turn over synthesized audio, no
Telegram/text channel involved:

```
espeak-ng -v en-us --stdout "what is on my calendar today" > question.wav
curl -X POST http://localhost:8080/hub/voice/turn \
  -F "user_id=hariz" \
  -F "audio=@question.wav;type=audio/wav" \
  -D - -o reply.wav
# -> X-Transcript / X-Reply-Text headers show what was heard and said;
#    reply.wav is real synthesized speech — play it or re-transcribe it
#    with the same STT provider to confirm.
```

Privacy/response router (Phase 9) — the exit criterion, live: a private
payload can't be spoken in Office mode, and the router still refuses even
in Desk mode (which normally always speaks via Reachy):

```
curl -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "hariz", "channel": "telegram", "text": "what is my salary this year"}'
# -> privacy: "sensitive", delivery_channel: "telegram" (never "reachy",
#    even though hariz is in the default Desk mode)

curl http://localhost:8080/hub/audit/hariz
# -> the routing decision, with "overridden": true recorded
```

Calendar (Phase 10) — a real "what's next" answer, and a meeting reminder
routed appropriately, both through Caddy:

```
curl -X POST http://localhost:8080/core/calendar/events \
  -H 'Content-Type: application/json' \
  -d '{"title": "Team Standup", "start": "2099-01-05T10:00:00Z", "end": "2099-01-05T10:30:00Z", "location": "Room 4"}'

curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what'"'"'s next"}'
# -> a real reply built from the event just added, privacy: "work-private"

# A meeting starting soon, checked for reminders via reachy-hub:
curl -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' -d '{"user_id": "hariz", "channel": "telegram", "text": "hi"}'
curl -X POST "http://localhost:8080/hub/calendar/check-reminders/hariz?within_minutes=15"
# -> delivery_channel routed away from "reachy" (Desk mode's default) —
#    calendar content is always work-private
```

Tasks (Phase 11) — recorded and retrieved conversationally, the exit
criterion, through Caddy:

```
curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "remind me to water the plants"}'

curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what are my tasks"}'
# -> "Your open tasks: water the plants." — a real recorded follow-up,
#    retrieved in a later turn

curl http://localhost:8080/core/tasks   # the same data via the direct API
```

Memory (Phase 12) — a work fact recorded and recalled conversationally,
through Caddy, with provenance/sensitivity attached and no transcript
dumping:

```
curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "remember that my manager'"'"'s email is alice@example.com"}'

curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "remember that I like green tea"}'

curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "do you remember alice@example.com"}'
# -> "Here's what I remember: my manager's email is alice@example.com." —
#    only the matching fact, not the green-tea fact or any other turn

curl "http://localhost:8080/core/memories/recall?q=alice@example.com"   # same data via the direct API
curl http://localhost:8080/core/memories                                # everything stored
```

RAG (Phase 13) — documents ingested, then answered from conversationally
with the source document/section named, through Caddy:

```
curl -X POST http://localhost:8080/core/documents \
  -H 'Content-Type: application/json' \
  -d '{"title": "Vacation Policy", "content": "# Requesting time off\nSubmit a request in Workday at least two weeks in advance.", "source": "hr.md"}'

curl -X POST http://localhost:8080/core/documents \
  -H 'Content-Type: application/json' \
  -d '{"title": "Expense Policy", "content": "# Filing expenses\nSubmit receipts in Concur within 30 days of purchase.", "source": "finance.md"}'

curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "search docs for requesting time off"}'
# -> "From 'Vacation Policy', section 'Requesting time off': Submit a
#    request in Workday at least two weeks in advance." — the *other*
#    ingested document, Expense Policy, is never surfaced for this query

curl "http://localhost:8080/core/documents/search?q=requesting+time+off"   # same data via the direct API
curl http://localhost:8080/core/documents                                   # every ingested document's title
```

Email (Phase 14) — drafted, blocked from sending until approved, then
sent for real via Mailpit, all through Caddy:

```
curl -X POST http://localhost:8080/core/emails/received \
  -H 'Content-Type: application/json' \
  -d '{"sender": "boss@example.com", "subject": "Q3 report", "body": "Can you send me the Q3 numbers?"}'

curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what'"'"'s in my inbox"}'

curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "draft email to boss@example.com about the Q3 numbers are attached"}'

curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "send draft boss@example.com"}'
# -> "That draft to boss@example.com needs approval first..." — refused,
#    nothing dispatched (check http://localhost:8025, Mailpit's UI, stays empty)

curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "approve draft boss@example.com"}'

curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "send draft boss@example.com"}'
# -> "Sent the email to boss@example.com..." — now check
#    http://localhost:8025 (Mailpit's UI) or its API:
curl http://localhost:8025/api/v1/messages

curl http://localhost:8080/core/emails/drafts   # same data via the direct API
```

No robot is auto-registered — `POST /hub/robots` above is a manual step.
Automatic registration (e.g. reachy-embodiment announcing itself to
reachy-hub on startup) isn't built yet; it's a natural fit for whichever
later phase adds real robot provisioning.

## Caddy

`Caddyfile` does path-based routing only (`/hub/*` -> reachy-hub, `/core/*`
-> companion-core). It does **not** implement authentication yet — see
docs/plan.md §9. Do not expose this port to the public Internet as
configured here; auth/TLS for real remote access is Phase 16 (remote
telepresence) territory.

## Known limitation

The Postgres migrations in `reachy_hub/postgres_registry.py`,
`postgres_session_store.py`, `postgres_telegram_chat_registry.py`,
`postgres_audit_log.py`, `companion_core/calendar/postgres_store.py`,
`companion_core/tasks/postgres_store.py`, `companion_core/memory/
postgres_store.py`, `companion_core/rag/postgres_store.py`, and
`companion_core/email/postgres_store.py` are each a single `CREATE TABLE
IF NOT EXISTS` (plus, for `rag/`, a one-time `CREATE EXTENSION IF NOT
EXISTS vector`) run at connect time — fine for the tables that exist
today, but not a real migration tool. Revisit (e.g. adopt Alembic) once a
schema actually needs to change under existing data, not just grow by one
more table.
