# deploy/homelab

Docker Compose deployment for `companion-core`, `reachy-hub`, PostgreSQL,
and a Caddy reverse proxy. Kubernetes is explicitly out of scope for initial
releases (see docs/plan.md §1 non-goals).

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
in a later turn and via the direct API (Phase 11); and, separately (not
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
`postgres_audit_log.py`, `companion_core/calendar/postgres_store.py`, and
`companion_core/tasks/postgres_store.py` are each a single `CREATE TABLE IF
NOT EXISTS` run at connect time — fine for the tables that exist today, but
not a real migration tool. Revisit (e.g. adopt Alembic) once a schema
actually needs to change under existing data, not just grow by one more
table.
