# Phase 24b command authorization verification — 2026-09-24

Implementation and isolated-fixture verification are complete: the
substring-based `robot_power_intent` matcher that could actuate real
standby/resume from ordinary conversational text is retired entirely, and
only an explicit structured command, an interactive action-button press
dispatching one, or an existing ADR 0011 consent flow can authorize a
consequential action now. This is not a live Telegram bot run or real
robot actuation — see "Not verified this session" below. See
[docs/phase-24b.md](../phase-24b.md).

## Negative conversational examples never actuate or suggest

`services/companion-core/tests/test_app.py::test_conversational_mentions_never_actuate_the_robot`
parametrizes every negative example from docs/phase-24b.md's exit-criteria
table — "How do I turn off Reachy?", "Don't turn off Reachy.", "I don't
want to turn off Reachy.", "Can you explain how to turn off Reachy?",
"What happens if I turn off Reachy?", "Is it safe to turn off Reachy?",
"How do I wake up Reachy?", "Don't wake up Reachy." — through a real
in-process companion-core → reachy-hub → reachy-embodiment chain with a
registered robot, and asserts the robot's real embodiment state never
becomes `sleep`. This proves the structural claim (`commands.parse`
returns `None` for all of them, so no code path can even reach
`HubClient.standby_robots`), independent of the classifier.

## Classifier resolves negatives to a non-`"request"` speech act, not merely fails to match

Per the exit criterion's stronger bar ("the classifier must resolve each
to a non-`request` speech_act, not merely fail to match"),
`services/companion-core/tests/test_command_suggestion.py::test_non_request_speech_acts_never_suggest`
drives a fixture LLM transport that returns a valid, schema-conforming
classification (`speech_act` ∈ `question`/`negation`/`hypothetical`/
`statement`/`other`) for "How do I turn off Reachy?" and asserts: the
classifier call happens (proving it was actually reached, not skipped),
and the ordinary conversational reply is returned unchanged — call-count
and output assertions, not inspection of classifier internals, per the
exit criterion's own methodology note.

## Explicit commands and alias equivalence

- `test_app.py::test_standby_command_parks_registered_robot_via_hub_and_embodiment`
  and `::test_resume_command_wakes_registered_robot_via_hub_and_embodiment`:
  `/reachy standby` and `/reachy wake` reach the real hub → embodiment
  chain and change the robot's real state (`sleep`/`idle`,
  `connected` False/True) — not a canned reply.
- `test_app.py::test_status_command_reports_registered_robots`: `/reachy
  status` reports the registered robot id.
- `test_app.py::test_telegram_alias_parses_to_the_identical_command_as_the_namespaced_form`:
  the Telegram flat alias `/standby` (posted over the `telegram` channel)
  produces the identical standby actuation and reply as `/reachy standby`.
- `services/companion-core/tests/test_commands.py` (new, pure-function unit
  tests, no HTTP): the namespaced form, the three Telegram flat aliases,
  unknown actions/aliases, plain text that merely mentions a command word,
  empty/whitespace-only text, and leading-whitespace tolerance all parse
  (or fail to parse) as specified — including that `/reachy gesture
  greeting` deliberately does **not** parse, since that action isn't
  wired to any hub call yet (AGENTS.md's "no speculative endpoints" rule).
- `test_command_suggestion.py::test_explicit_command_never_reaches_the_classifier`:
  `/reachy standby` never calls the LLM transport at all — the explicit
  parser is checked first and short-circuits before the classifier.

## Suggestion, not action

`test_command_suggestion.py::test_high_confidence_request_produces_a_suggestion_not_an_answer`:
a fixture classifier response with `speech_act: "request"` and high
confidence for "Could you put Reachy to sleep?" produces a reply
containing the literal `/reachy standby` suggestion text, and only one LLM
call happens total (the classifier's) — the model's own answer call never
happens, proving the suggestion *replaces* the answer rather than running
alongside it, and (structurally, via the command parser above) never
itself calls the standby/resume path.

## Classifier fail-closed: timeout, malformed output, low confidence

- `test_classifier_failure_falls_back_silently_to_the_ordinary_answer`:
  a non-JSON classifier response falls back to the ordinary reply, with
  no error surfaced.
- `test_classifier_timeout_falls_back_silently_to_the_ordinary_answer`: a
  503 from the classifier's own call falls back the same way, and —
  important given the classifier is a QoL layer, not a user-facing
  answer — its failure is **not** recorded in the operator-visible LLM
  usage ledger (`GET /llm/usage` shows `errors: 0`), since it uses a
  dedicated discarding usage sink rather than the shared store.
- `test_low_confidence_request_never_suggests`: a `"request"`
  classification below the fixed confidence threshold still falls back to
  the ordinary answer.
- `test_classifier_is_never_called_for_text_unrelated_to_the_robot`: text
  that never mentions "reachy" never invokes the classifier at all (the
  cost/latency pre-filter), confirmed by call-count assertion.

## Action-button dispatch

`clients/operator-ui/tests/chat.test.cjs`'s new case ("web chat renders
command autocomplete and dispatches suggested-command buttons", Chromium/
Playwright, fixture HTTP server): typing `/reachy sta` shows a filtered
autocomplete hint that fills the textbox on click; a suggestion reply
("Use /reachy standby.") renders a real `<button>` (not HTML re-parsed
from the reply text — no `.chat-command-suggestion` node exists on a
non-suggestion reply, and the fixture's XSS-payload reply in the sibling
test still produces zero `script`/`img` elements); clicking it re-sends
the literal `/reachy standby` text through the normal `/messages` POST
path — the click is the authorization event, not the sentence that
produced the button.

## Telegram command registration

`services/reachy-hub/tests/test_telegram.py::test_telegram_startup_registers_flat_command_aliases`:
against a fake Telegram Bot API (`httpx.MockTransport`, no real network),
starting the hub with Telegram polling enabled calls `setMyCommands` with
exactly `{standby, wake, reachy_status}` — the flat aliases, not the
namespaced `/reachy <action>` form, since Telegram's `BotCommand.command`
field cannot contain a space.

## Full regression suite

- `ruff check services shared`: clean.
- `pytest services shared`: **466 passed, 16 skipped** (pre-existing,
  espeak-dependent), no failures — includes every test above plus the
  full pre-existing suite (calendar/tasks/memory/RAG/email/accounts/
  LLM routing/websearch/etc.), confirming the retirement of
  `robot_power_intent` and the new command/classifier wiring didn't
  regress anything else in the deterministic-intent chain.
- `clients/operator-ui/tests/*.test.cjs` (Chromium/Playwright): all 5
  suites pass (`accounts` ×2, `chat` ×2, `websearch`).

## Not verified this session

- **No live Telegram bot run.** `setMyCommands` registration and the
  `/standby`/`/wake`/`/reachy_status` aliases were verified only against
  a fake Bot API fixture, not the real Telegram servers.
- **No real robot actuation.** `/reachy standby`/`wake` were verified
  against the real hub → embodiment HTTP chain with a *simulated* robot
  backend (the same in-process chain `test_app.py` has always used for
  this feature) — not physical Nano/Reachy hardware. Per AGENTS.md,
  physical acceptance additionally requires the owner present and
  supervising, which this session did not attempt.
- **Confidence threshold and classification prompt are unvalidated
  against a real model.** All classifier tests use a fixture LLM
  transport returning controlled, schema-conforming (or deliberately
  malformed) JSON; no real local/cloud model has classified any of the
  exit criterion's examples yet, so the prompt's real-world accuracy
  (as opposed to the fail-closed *mechanism* around it, which is fully
  covered) is unverified.
- **Web chat command autocomplete's UX is covered by exactly one
  Playwright scenario** (filter-and-fill), not a broader interaction
  matrix (e.g. keyboard navigation of the hint list).
