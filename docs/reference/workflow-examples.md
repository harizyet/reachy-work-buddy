# Workflow API examples

Run these only against a disposable simulation stack configured with the
[deployment guide](../deployment.md#simulation). Examples create records,
change sessions, and may send mail to the test Mailpit instance. They are
manual smoke checks, not installation steps. The examples use the owner bearer for hub and the dedicated service credential
for direct core calls. Load these variables from the protected deployment env
without printing them. `OWNER_USER_ID` must be `default-user` for these examples.
Set `CORE_URL` to the core URL exposed **only by your disposable test override**;
the Caddy `/core/` data proxy is closed. Do not publish core for normal use.
Normal operators should use the authenticated GUI.

Sessions (Phase 5) — two separate `curl` calls standing in for two
different channels/clients, same user, one shared conversation:

```
curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "default-user", "channel": "reachy", "text": "whats on my calendar"}'

curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "default-user", "channel": "telegram", "text": "continue that"}'
# -> same session_id/conversation_id as the first call, active_channel now
#    "telegram", and companion-core's turn counter advanced to 2.

curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" http://localhost:8080/hub/sessions/default-user
```

Operating modes (Phase 6) — same text, different mode, different resolved
`delivery_channel`. Since Phase 19, the PATCH needs a configured bearer
token (shown below) or an owner cookie with the CSRF header. Use a public
greeting and a fresh disposable owner session for this example; previous private
context can keep generated follow-ups private:

```
curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "default-user", "channel": "telegram", "text": "hello"}'
# -> delivery_channel: "reachy" (Desk is the default mode)

curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X PATCH http://localhost:8080/hub/sessions/default-user/mode \
  -H 'Content-Type: application/json' -d '{"interaction_mode": "office"}'

curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "default-user", "channel": "telegram", "text": "hello"}'
# -> delivery_channel: "phone" — same text, mode alone changed the routing
```

Telegram (Phase 7) — optional, set `TELEGRAM_BOT_TOKEN` (and
`TELEGRAM_DEFAULT_USER_ID`, matching the `user_id` used above) in `.env`
plus the explicit private `TELEGRAM_OWNER_CHAT_ID` before startup to enable it. Unset, `reachy-hub` runs fine
without any Telegram code path active. With it set: message your bot on
Telegram and `curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" http://localhost:8080/hub/sessions/YOUR_USER_ID` shows
`active_channel: "telegram"` with the same `session_id` as any prior
Reachy-channel message for that user — verified against a real bot and a
real Telegram account, not just curl.

Voice (Phase 8) — a real conversation turn over synthesized audio, no
Telegram/text channel involved:

```
espeak-ng -v en-us --stdout "what is on my calendar today" > question.wav
curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X POST http://localhost:8080/hub/voice/turn \
  -F "user_id=default-user" \
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
curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "default-user", "channel": "telegram", "text": "what is my salary this year"}'
# -> privacy: "sensitive", delivery_channel: "telegram" (never "reachy",
#    even though default-user is in the default Desk mode)

curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" http://localhost:8080/hub/audit/default-user
# -> the routing decision, with "overridden": true recorded
```

Calendar (Phase 10) — a real "what's next" answer, and a meeting reminder
routed appropriately, through the test stack:

```
curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/calendar/events \
  -H 'Content-Type: application/json' \
  -d '{"title": "Team Standup", "start": "2099-01-05T10:00:00Z", "end": "2099-01-05T10:30:00Z", "location": "Room 4"}'

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what'"'"'s next"}'
# -> a real reply built from the event just added, privacy: "work-private"

# A meeting starting soon, checked for reminders via reachy-hub:
curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' -d '{"user_id": "default-user", "channel": "telegram", "text": "hi"}'
curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X POST "http://localhost:8080/hub/calendar/check-reminders/default-user?within_minutes=15"
# -> delivery_channel routed away from "reachy" (Desk mode's default) —
#    calendar content is always work-private
```

Tasks (Phase 11) — recorded and retrieved conversationally, the exit
criterion, through the test stack:

```
curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "remind me to water the plants"}'

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what are my tasks"}'
# -> "Your open tasks: water the plants." — a real recorded follow-up,
#    retrieved in a later turn

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" $CORE_URL/tasks   # the same data via the direct API
```

Memory (Phase 12) — a work fact recorded and recalled conversationally,
through the test stack, with provenance/sensitivity attached and no transcript
dumping:

```
curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "remember that my manager'"'"'s email is alice@example.com"}'

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "remember that I like green tea"}'

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "do you remember alice@example.com"}'
# -> "Here's what I remember: my manager's email is alice@example.com." —
#    only the matching fact, not the green-tea fact or any other turn

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" "$CORE_URL/memories/recall?q=alice@example.com"   # same data via the direct API
curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" $CORE_URL/memories                                # everything stored
```

RAG (Phase 13) — documents ingested, then answered from conversationally
with the source document/section named, through the test stack:

```
curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/documents \
  -H 'Content-Type: application/json' \
  -d '{"title": "Vacation Policy", "content": "# Requesting time off\nSubmit a request in Workday at least two weeks in advance.", "source": "hr.md"}'

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/documents \
  -H 'Content-Type: application/json' \
  -d '{"title": "Expense Policy", "content": "# Filing expenses\nSubmit receipts in Concur within 30 days of purchase.", "source": "finance.md"}'

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "search docs for requesting time off"}'
# -> "From 'Vacation Policy', section 'Requesting time off': Submit a
#    request in Workday at least two weeks in advance." — the *other*
#    ingested document, Expense Policy, is never surfaced for this query

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" "$CORE_URL/documents/search?q=requesting+time+off"   # same data via the direct API
curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" $CORE_URL/documents                                   # every ingested document's title
```

Email (Phase 14) — drafted, blocked from sending until approved, then
sent for real via Mailpit, through the test stack:

```
curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/emails/received \
  -H 'Content-Type: application/json' \
  -d '{"sender": "boss@example.com", "subject": "Q3 report", "body": "Can you send me the Q3 numbers?"}'

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what'"'"'s in my inbox"}'

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "draft email to boss@example.com about the Q3 numbers are attached"}'

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "send draft boss@example.com"}'
# -> "That draft to boss@example.com needs approval first..." — refused,
#    nothing dispatched (check http://localhost:8025, Mailpit's UI, stays empty)

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "approve draft boss@example.com"}'

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST $CORE_URL/conversation \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "send draft boss@example.com"}'
# -> "Sending the email to boss@example.com in about 10 minutes..." — see
#    ADR 0011 below for the delay; check http://localhost:8025 (Mailpit's
#    UI) or its API once the window has passed:
curl http://localhost:8025/api/v1/messages

curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" $CORE_URL/emails/drafts   # same data via the direct API
```

ADR 0011 (destructive-action consent, voice exclusion, delayed send) —
Use one user/session throughout this check. Set `MEMORY_ID` and `DRAFT_ID`
from the corresponding API response before trying the undo commands. Memory
forgetting requires text confirmation, voice is refused outright,
and email sending is delay-queued with an undo window, through the test stack:

```
curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "default-user", "channel": "web", "text": "remember that my manager is Alice"}'

curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "default-user", "channel": "web", "text": "forget Alice"}'
# -> "To permanently forget \"my manager is Alice\", say: yes forget Alice"

# Voice can never confirm a destructive action — say the confirmation out
# loud through the real voice pipeline and it's refused, whatever it
# transcribes to:
espeak-ng -v en-us --stdout "yes forget Alice" > confirm.wav
curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X POST http://localhost:8080/hub/voice/turn \
  -F "user_id=default-user" -F "audio=@confirm.wav;type=audio/wav" -D - -o reply.wav
# -> X-Reply-Text: "For your security, I can't accept that confirmation by
#    voice. Please confirm from a text channel like Telegram."

curl -H "Authorization: Bearer $REMOTE_UI_TOKEN" -X POST http://localhost:8080/hub/messages \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "default-user", "channel": "web", "text": "yes forget Alice"}'
# -> "Forgotten: ..." — gone from /core/memories, but never actually
#    deleted: it's a soft delete, so the undo always works:
curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST "$CORE_URL/memories/${MEMORY_ID}/restore"

# Email sending queues instead of dispatching, and can be cancelled before
# its ~10-minute window elapses:
curl -H "X-Reachy-Service-Token: $ACCOUNTS_SERVICE_TOKEN" -X POST "$CORE_URL/emails/drafts/${DRAFT_ID}/cancel-send"
```

For browser calls and telepresence, follow the [operator guide](../operator-guide.md#calls-and-telepresence).
