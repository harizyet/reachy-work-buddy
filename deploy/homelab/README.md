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
(Postgres 16, Caddy 2): all six containers start
(`reachy-embodiment` now builds with `torch`/`silero-vad`, `reachy-hub`
with `faster-whisper` and `espeak-ng`, `companion-core` now connects to
Postgres for its persistent stores); the robot registry, `AgentSession`
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
a spoken ("voice", via `POST /hub/voice/turn` with real synthesized
speech, real STT transcription) attempt to confirm a pending memory-forget
was refused while the identical typed confirmation succeeded — the memory
genuinely gone from `/core/memories` and then restorable — an email send
was queued (not dispatched) for ~10 minutes, cancelled with Mailpit
staying at zero messages, then re-queued and left running for the full
real ~10-minute delay, producing a real SMTP message in Mailpit once due
(ADR 0011); a real (non-browser) `aiortc` Python client negotiated a real
WebRTC call through Caddy (`POST /hub/webrtc/offer`), sent real
synthesized speech, and got real non-silent synthesized reply audio back,
with the real embodiment's `last_behaviour` observed transitioning through
`listening`/`thinking`/`speaking` over the same call, and the PWA's own
static files served correctly through Caddy at `/hub/app/` (Phase 15, ADR
0012); and, separately (not
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

# These core debug proxies need REMOTE_UI_TOKEN configured in both services.
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
`delivery_channel`. Since Phase 19, the PATCH needs a configured bearer
token (shown below) or an owner cookie with the CSRF header. Use a public
greeting and a fresh `mode-demo` user for this example; previous private
context can keep generated follow-ups private:

```
curl -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "mode-demo", "channel": "telegram", "text": "hello"}'
# -> delivery_channel: "reachy" (Desk is the default mode)

curl -X PATCH http://localhost:8080/hub/sessions/mode-demo/mode \
  -H "Authorization: Bearer $REMOTE_UI_TOKEN" \
  -H 'Content-Type: application/json' -d '{"interaction_mode": "office"}'

curl -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "mode-demo", "channel": "telegram", "text": "hello"}'
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
# -> "Sending the email to boss@example.com in about 10 minutes..." — see
#    ADR 0011 below for the delay; check http://localhost:8025 (Mailpit's
#    UI) or its API once the window has passed:
curl http://localhost:8025/api/v1/messages

curl http://localhost:8080/core/emails/drafts   # same data via the direct API
```

ADR 0011 (destructive-action consent, voice exclusion, delayed send) —
memory forgetting requires text confirmation, voice is refused outright,
and email sending is delay-queued with an undo window, all through Caddy:

```
curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "remember that my manager is Alice"}'

curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "forget Alice"}'
# -> "To permanently forget \"my manager is Alice\", say: yes forget Alice"

# Voice can never confirm a destructive action — say the confirmation out
# loud through the real voice pipeline and it's refused, whatever it
# transcribes to:
espeak-ng -v en-us --stdout "yes forget Alice" > confirm.wav
curl -X POST http://localhost:8080/hub/voice/turn \
  -F "user_id=hariz" -F "audio=@confirm.wav;type=audio/wav" -D - -o reply.wav
# -> X-Reply-Text: "For your security, I can't accept that confirmation by
#    voice. Please confirm from a text channel like Telegram."

curl -X POST http://localhost:8080/core/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "yes forget Alice"}'
# -> "Forgotten: ..." — gone from /core/memories, but never actually
#    deleted: it's a soft delete, so the undo always works:
curl -X POST http://localhost:8080/core/memories/<memory_id>/restore

# Email sending queues instead of dispatching, and can be cancelled before
# its ~10-minute window elapses:
curl -X POST http://localhost:8080/core/emails/drafts/<draft_id>/cancel-send
```

Call Reachy (Phase 15, ADR 0012) — open the PWA in a browser on the same
machine as the Docker host (see the ADR for the known cross-machine
limitation), register a robot first exactly as above, then:

```
open http://localhost:8080/hub/app/   # or just navigate there in a browser
```

Enter a `user_id`/`robot_id` (matching a registered robot), click "Call
Reachy," allow microphone access, then hold the talk button, speak, and
release. The status text shows `listening` -> `thinking` -> `speaking` as
the real embodiment's behaviour changes in step, and the reply plays back
through the browser/earbuds — never through Reachy's speaker. There's no
browser available in this repo's own dev/CI environment, so the live
verification above used a real `aiortc` Python client as a stand-in
"browser" instead — see `services/reachy-hub/tests/test_webrtc_call_live.py`
for the same flow, automated.

No robot is auto-registered — `POST /hub/robots` above is a manual step.
Automatic registration (e.g. reachy-embodiment announcing itself to
reachy-hub on startup) isn't built yet; it's a natural fit for whichever
later phase adds real robot provisioning.

## Caddy

`Caddyfile` routes `/hub/*` to reachy-hub and `/core/*` to companion-core.
Hub enforces authentication on remote control and the Phase 19 operator
API; Caddy blocks `/core/settings/*` and `/core/llm/*` to prevent bypassing
those gates. Other historical core/debug/conversation APIs retain their
trusted-network access model. Caddy does not terminate TLS in this setup;
use the documented homelab/VPN boundary or configure HTTPS before remote
use. See [ADR 0016](../../docs/adr/0016-operator-ui.md).

## Known limitation

The Postgres schema initializers in `reachy_hub/postgres_registry.py`,
`postgres_session_store.py`, `postgres_telegram_chat_registry.py`,
`postgres_audit_log.py`, `companion_core/calendar/postgres_store.py`,
`companion_core/tasks/postgres_store.py`, `companion_core/memory/
postgres_store.py`, `companion_core/rag/postgres_store.py`,
`companion_core/email/postgres_store.py`, and `companion_core/consent/
postgres_store.py` are each a single `CREATE TABLE IF NOT EXISTS` (plus,
for `rag/`, a one-time `CREATE EXTENSION IF NOT EXISTS vector`) run at
connect time — fine for the tables that exist today, but not a real
migration tool. This bit ADR 0011 in particular: `forgotten_at`
(`memories`) and `dispatch_at` (`email_drafts`) are new columns on
existing tables, which `CREATE TABLE IF NOT EXISTS` does not add to an
already-existing table — a deployment from before that ADR needs a manual
`ALTER TABLE ... ADD COLUMN` before upgrading (a fresh volume, as used for
all the live verification in this README, has no such problem). Revisit
(e.g. adopt Alembic) once a schema actually needs to change under existing
data. Phase 19 adds only new tables; it does not require a reset of a
current Phase 18 database. Do not use volume deletion to upgrade existing
user data.

## Operator dashboard (Phase 19)

Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and a random `SESSION_SECRET_KEY`
in your gitignored `.env` before starting the stack, then open
[http://localhost:8080/hub/ui/](http://localhost:8080/hub/ui/).
The password creates an account only when the `users` table is empty;
changing the environment later does not reset the saved password. Keep the
signing key stable across restarts. Set `SESSION_COOKIE_SECURE=true` when
serving through HTTPS. Local HTTP access still assumes the trusted
homelab/VPN boundary documented above.

The dashboard monitors core and registered robots, reports LLM calls,
tokens, errors and latency, and edits LLM configuration immediately. Load
the same user ID your conversational channel uses (normally
`TELEGRAM_DEFAULT_USER_ID`, default `default-user`) to change mode/DND or
see its activity and queued notifications. The session must already exist
from a conversation. Telegram's indicator now reports live poll freshness
and sanitized failures.

For OVMS, enter its reachable base URL including `/v1`, the exact model
name from `GET /v1/models`, and leave the API key blank if none is required.
`localhost` inside companion-core's container is **that container**, not
the Docker host. To reach OVMS running on the host on Linux, add this
Compose override and use `http://host.docker.internal:8000/v1`:

```yaml
services:
  companion-core:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

A server elsewhere on the LAN can instead use its LAN URL. A hosted
compatible provider uses the same form with its base URL and key. Phase 19
now supports both provider roles and hybrid routing; see Phase 21 below.
Blank key input preserves the saved key; the checkbox removes it. Keys are
masked in API responses but stored plaintext in Postgres and backups.

Owner-cookie access also works in telepresence; the old browser token
field is removed. Bearer tokens still work for API clients, including the
newly gated session PATCH routes:

```bash
curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" \
  -H 'Content-Type: application/json' \
  -X PATCH http://localhost:8080/hub/sessions/default-user/dnd \
  -d '{"dnd":true}'
```

Core settings and usage cannot be accessed through Caddy's `/core/` debug
proxy. Use the authenticated `/hub/settings/llm` and `/hub/llm/usage`
endpoints. Phase 19 adds only new tables, so it does not require deleting
an existing Phase 18 Postgres volume.


## Web chat (Phase 20)

Open `/hub/ui/`, log in, and choose Chat. It uses the existing messages API
and the configured `TELEGRAM_DEFAULT_USER_ID` (default `default-user`). Use
the same user ID across channels to preserve session context; a first web
message can also start a new session. The user selector is shared with
Overview, and chat displays mode, DND, and active channel.

Replies appear in the browser regardless of routing metadata. The visible
transcript clears on refresh/logout/user changes; “Clear view” only clears
that display. Core's in-memory context and durable work memory are separate.
The UI verifies login before sending, but the historical `/hub/messages`
API remains open within the trusted private-network boundary. No new chat
history endpoint, schema migration, environment setting, or dependency is
needed.

Telegram status now includes a last successful poll, sanitized error, and
`healthy`. It becomes healthy after the first successful poll (idle long
polls can take 25 seconds), fails on a poll error, and becomes stale after
60 seconds without success. The indicator measures polling, not outbound
message delivery; long message processing can also make it stale. Web chat
remains usable during Telegram failures as long as hub/core are available.

Phase 20 was verified in an isolated `phase20verify` Compose project with
Chromium and real OVMS inference. An intentionally invalid test bot token
produced a real Telegram HTTP 401 while web messages still received replies.
The Telegram-channel continuity test used `POST /messages`, not a real
Telegram-account exchange. The disposable stack was removed afterward;
the existing OVMS container was left running. Do not invalidate an actual
bot token or remove user volumes to reproduce the outage test.


## Hybrid LLM routing (Phase 21)

Configure local and optional cloud providers in Overview → Language model.
Use each provider's compatible chat endpoint base URL (normally ending in
`/v1`) and exact model name. Native vendor APIs need a compatible gateway;
no native vendor SDK adapter is included. Cloud configuration and inference
are owned by core and stored in Postgres, not Compose environment variables.
Select the standing routing policy, or use Chat's one-message frontier toggle.

Upgrading a current Phase 19/20 database requires no reset: startup adds
nullable `llm_usage_log.escalation_reason` idempotently. Existing config and
usage survive. Cloud requests send bounded conversation history; keys remain
plaintext in the database and backups, with masked operator responses.

For an assisted hosted-provider verification, put `CLOUD_LLM_BASE_URL`,
`CLOUD_LLM_MODEL`, and `CLOUD_LLM_API_KEY` in gitignored `.env.local`, never
chat. These are verification inputs, not automatically imported runtime
settings. The operator UI is the normal configuration path. The Phase 21
live check used an isolated stack and OVMS for both roles, proving local
inference, error fallback, manual dispatch, usage and persistence. A real
hosted-provider check remains pending credentials. See
[ADR 0018](../../docs/adr/0018-hybrid-llm-routing.md).
