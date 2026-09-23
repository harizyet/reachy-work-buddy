# Workflow API examples

Run these only against a disposable simulation stack configured with the
[deployment guide](../deployment.md#simulation). Examples create records,
change sessions, and may send mail to the test Mailpit instance. They are
manual smoke checks, not installation steps. Protected hub mutations need
an owner cookie plus CSRF or an Authorization bearer header; commands below
that omit those headers must be supplied with them. Core debug proxies also
need REMOTE_UI_TOKEN in both services.

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
Telegram and `curl http://localhost:8080/hub/sessions/YOUR_USER_ID` shows
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
Use one user/session throughout this check. Set `MEMORY_ID` and `DRAFT_ID`
from the corresponding API response before trying the undo commands. Memory
forgetting requires text confirmation, voice is refused outright,
and email sending is delay-queued with an undo window, all through Caddy:

```
curl -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "consent-demo", "channel": "web", "text": "remember that my manager is Alice"}'

curl -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "consent-demo", "channel": "web", "text": "forget Alice"}'
# -> "To permanently forget \"my manager is Alice\", say: yes forget Alice"

# Voice can never confirm a destructive action — say the confirmation out
# loud through the real voice pipeline and it's refused, whatever it
# transcribes to:
espeak-ng -v en-us --stdout "yes forget Alice" > confirm.wav
curl -X POST http://localhost:8080/hub/voice/turn \
  -F "user_id=consent-demo" -F "audio=@confirm.wav;type=audio/wav" -D - -o reply.wav
# -> X-Reply-Text: "For your security, I can't accept that confirmation by
#    voice. Please confirm from a text channel like Telegram."

curl -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "consent-demo", "channel": "web", "text": "yes forget Alice"}'
# -> "Forgotten: ..." — gone from /core/memories, but never actually
#    deleted: it's a soft delete, so the undo always works:
curl -X POST "http://localhost:8080/core/memories/${MEMORY_ID}/restore"

# Email sending queues instead of dispatching, and can be cancelled before
# its ~10-minute window elapses:
curl -X POST "http://localhost:8080/core/emails/drafts/${DRAFT_ID}/cancel-send"
```

For browser calls and telepresence, follow the [operator guide](../operator-guide.md#calls-and-telepresence).
