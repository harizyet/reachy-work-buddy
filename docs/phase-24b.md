# Phase 24b — Structured command and intent authorization

Status: implemented and isolated-fixture verified (2026-09-24) — see
HANDOVER.md for what remains open (live Telegram bot run, real robot
actuation). One of two independent tracks under
**Phase 24 — QoL improvements**, alongside [Phase 24a](phase-24a.md)'s
search-assisted assistant; the two share a phase number as general
assistant usefulness/safety improvements sequenced before Phase 25's owner
recognition, not because either depends on the other. Builds on the
existing deterministic-intent-before-LLM precedence (AGENTS.md: "Preserve
deterministic intent/consent precedence... The LLM has no authority to
bypass an action gate") and the persona/routing plumbing already used by
Phases 19–22b; does not depend on Phase 22b hardware or Phase 24a.

## Motivation

`companion_core.robot_power_intent` — implemented and live in Phase 22b's
remote standby/resume feature — matches standby/wake phrases as plain
substrings:

```python
any(phrase in text.lower() for phrase in STANDBY_PHRASES)
```

This does not distinguish an imperative command from a question, negation,
hypothetical, or explanation request. All of the following currently match
and would actuate the real robot on an owner-authenticated channel, exactly
as if they were commands:

```text
How do I turn off Reachy?
Don't turn off Reachy.
I don't want to turn off Reachy.
Can you explain how to turn off Reachy?
What happens if I turn off Reachy?
Is it safe to turn off Reachy?
How do I wake up Reachy?
Don't wake up Reachy.
```

This is a known, currently open issue in shipped code (see HANDOVER),
deliberately left unpatched pending this phase's redesign rather than
patched piecemeal in the existing matcher — see Implementation implications
below for why a better negation/question regex is not the fix.

The underlying problem is architectural, not specific to standby/resume:
**free-form conversational text is not, by itself, sufficient
authorization for an executable action just because it contains a matching
phrase.** Trying to make an increasingly complex keyword/regex matcher
understand negation, questions, quotations, hypotheticals and instructional
discussion is a losing game — the fix is to stop asking substring matching
to carry that weight at all, and separate three responsibilities that are
currently conflated in one keyword check: understanding what the user
means, authorizing an action, and executing it.

## Required behaviour

### Revised command model

```
incoming text
      │
      ▼
explicit command parser
      │
      ├── valid executable command
      │        ↓
      │   authorization / policy
      │        ↓
      │      action
      │
      └── ordinary text
               ↓
         deterministic intents
               ↓
             LLM
               ↓
        optional intent suggestion
```

- **Explicit commands** use a namespaced slash-command syntax internally,
  parsed deterministically before both the existing deterministic-intent
  chain and the generic LLM conversation branch — same precedence position
  `robot_power_intent` already occupies today, just replacing substring
  matching with an unambiguous parser. Recommended internal/canonical form:

  ```text
  /reachy standby
  /reachy wake
  /reachy status
  /reachy gesture greeting
  ```

  This namespaced form is the one users type in web chat, where autocomplete
  can present `/reachy <action>` directly. Telegram is a separate case (see
  Channel handling): the Bot API's `BotCommand.command` field cannot contain
  a space, so `/reachy standby` cannot itself be registered as one Telegram
  menu entry — flat aliases (`/standby`, `/wake`, `/reachy_status`) are
  registered there instead, and both forms parse to the identical structured
  `Command`. The namespaced form remains preferred/documented as the
  canonical one since it scales to future assistant commands (search,
  persona, settings) without collision, where a flat global command
  namespace eventually would; flat aliases exist only where a channel's own
  command-registration API requires them.
- A successfully parsed command becomes a structured internal value before
  anything downstream sees it — not a re-matched string:

  ```text
  Command
  ├── namespace: reachy
  └── action: standby
  ```

  Only this structured `Command` value is permitted to directly invoke the
  corresponding physical/consequential action. No code path may construct
  one from free-form text matching alone.
- **Natural-language intent recognition remains useful but is never
  authoritative.** A dedicated, separate suggestion classifier — not the
  retired substring matcher (see Implementation implications) — classifies
  free-form text into both an intent and a **speech act**, e.g. "Could you
  put Reachy to sleep?" → `{"intent": "robot_standby", "confidence": 0.97,
  "speech_act": "request"}` versus "How do I turn off Reachy?" →
  `{"intent": "robot_standby", "confidence": 0.99, "speech_act":
  "question"}`. A suggestion is offered only when `speech_act == "request"`
  **and** confidence clears a fixed threshold; questions, negations,
  hypotheticals and quoted/reported speech (`speech_act` values other than
  `"request"`) produce no suggestion at all — the assistant just answers
  normally, per the interaction-tiers table below. This is the one place a
  local LLM call is warranted in this phase: classification assists UX, but
  deterministic code still owns the suggest/don't-suggest decision and,
  regardless of the classifier's output, never owns authorization — a
  recognized intent triggers a *suggestion*, never the action itself:

  ```text
  It sounds like you want to put Reachy into standby.
  Use /reachy standby.
  ```

  or, on interfaces that support interactive controls, a rendered action
  button (`[ Put Reachy in standby ]`) that itself dispatches the
  structured command when pressed — the button press is the explicit
  authorization step, not the sentence that triggered its display.
- This yields three interaction tiers:

  | Input | Example | Behaviour |
  |---|---|---|
  | Explicit command | `/reachy standby` | Execute after normal authorization checks |
  | High-confidence natural-language intent | "Could you put Reachy to sleep?" | Suggest command or action button; do not execute |
  | Ordinary conversational mention | "How do I turn off Reachy?" | Answer the question normally — no intent match, no suggestion, no action |

  The design principle this phase establishes: **understanding intent and
  authorizing an action remain separate responsibilities.** Conversational
  language may express or imply intent, but consequential actions require
  an explicit structured command, an interactive-control press that
  dispatches one, or an existing confirmation/consent path (ADR 0011).

### Suggestion classifier: constrained output and fail-closed behaviour

The classifier's output is a fixed, validated structure, not free model
prose to be pattern-matched after the fact:

```json
{
  "intent": "robot_standby",
  "speech_act": "request",
  "confidence": 0.96
}
```

`intent` and `speech_act` are drawn from fixed enums the code defines (not
open strings the model invents), and `confidence` is a required numeric
field. A response that doesn't parse against this schema is not
"best-effort interpreted" — it is a classifier failure (see below).

The classifier is a QoL enhancement layered on top of the ordinary
conversational branch, so **its own failure must never degrade or block
that branch, and must never itself become a path to a suggestion**:

```text
classifier unavailable / timeout
invalid JSON / schema mismatch
unknown or missing speech_act
missing confidence
        ↓
   NO suggestion
        ↓
continue ordinary conversation, unchanged
```

Concretely: failure, timeout, malformed structured output, or an
unrecognized/missing `speech_act` or `confidence` from the suggestion
classifier is treated identically to `speech_act != "request"` — as "no
actionable suggestion." The ordinary conversational branch proceeds exactly
as it would if the classifier were never called; the failure is not
surfaced to the user as an error, and it certainly never falls back to
guessing an actionable intent from the raw classifier output or from the
original text. This mirrors this codebase's existing "provider failure is
not a crash" doctrine (Phase 21's LLM routing, Phase 24a's search failure
handling) applied to a non-authoritative classification step instead of an
answer-producing one — here the safe default on failure is simply silence,
since there is no obligation to say anything at all.

### Suggestion scope boundary: narrow requests only, never at the expense of the answer

The suggestion replaces the model's own answer for that turn (Required
behaviour above), not both a suggestion and an answer together. For a
clearly action-only request ("Could you put Reachy to sleep?") that's the
whole point — there's no separate question to answer. But a message that
mixes a genuine question with an incidental action-ish clause ("Can you
explain what standby does, and if appropriate put Reachy to sleep?")
would be poorly served by a bare "Use /reachy standby." reply that
discards the explanation the user actually asked for.

This is a UX boundary, not a safety rule (unlike everything else in this
document, getting it wrong produces an unhelpful reply, not an
unauthorized action) — so it's deliberately narrower than a schema
constraint: the classifier's prompt should treat `speech_act == "request"`
as reserved for messages that are *only* asking for the action itself,
with nothing else worth answering, and classify anything with additional
substantive content (an embedded question, an explanation request, a
conditional worth addressing on its own) as `"statement"` or `"other"` —
i.e. no suggestion, ordinary answer — rather than as a request whose
suggestion would silently drop that content. v1's scope (`robot_standby`/
`robot_resume` from short, plainly imperative phrasings) doesn't exercise
this edge — the exit-criteria examples are all either clean requests or
clean non-requests — but it must not regress as more intents are added
under this same classifier in later phases. Widening `"request"`'s scope
to also produce a suggestion *alongside* an answer, rather than treating
mixed messages as non-actionable, is a possible future direction, but not
one this phase attempts; it would need its own reply-composition design
(how the suggestion and the answer are both shown), not just a schema
change.

### Scope of explicit-command-only actions

Explicit command syntax is required wherever a false-positive actuation
would materially affect the user, environment, privacy, or an external
system:

```text
robot standby / wake
camera activation
microphone activation
telepresence
external message/email sends
calendar writes
other consequential control actions
```

Email sends and calendar writes already have their own explicit
preview/confirm and text-only consent gates (ADR 0011); this phase's
command parser is an additional, earlier deterministic gate specifically
for actions — like robot standby/wake today — that currently have no
confirmation step at all and rely solely on phrase matching. It does not
replace ADR 0011's existing consent flow for the actions that already have
one.

Very low-risk, bounded, reversible actions may remain eligible for
natural-language-triggered execution where separately approved by policy —
for example, named pre-recorded behaviours (`greeting`, `acknowledgement`,
a happy animation) already accepted by the owner as a lower-risk class
(AGENTS.md's named-behaviour-playback exception). This phase does not
change that existing exception; it only tightens the actions that
currently have *no* structured gate at all.

### Channel handling

Command meaning is channel-independent — one shared parser, not a
per-channel reimplementation:

```text
Telegram
Web chat
future clients
      ↓
shared deterministic command parser
      ↓
authorization / policy
      ↓
Hub / Core / Embodiment action
```

- **Telegram** already has a native slash-command UX (command menu,
  autocomplete), but its Bot API's `BotCommand.command` field cannot
  contain a space, so `/reachy standby` cannot be registered as a single
  menu entry there. Telegram registers flat first-class aliases instead —
  `/standby`, `/wake`, `/reachy_status` — via its existing bot-command-list
  API; each alias parses to the same structured `Command` the namespaced
  form would (`/standby` → `Command(namespace="reachy", action="standby")`).
  Both `/reachy standby` and `/standby` are accepted as input text on every
  channel; only Telegram's *registered menu* is restricted to the flat
  aliases, since that restriction is Telegram's own API constraint, not a
  property of the command model itself.
- **Web chat** uses the same shared parser (not a second implementation)
  and may additionally render command autocomplete and action buttons for
  suggested intents.
- The parser itself lives once, in companion-core (cognition/command
  concern, same boundary reasoning as existing deterministic-intent
  modules), and is invoked identically regardless of which channel the text
  arrived through — reachy-hub continues to own only channel transport, per
  ADR 0001.

## Non-goals

- **No general natural-language command execution**, even at high
  confidence. A 0.97-confidence intent classification is a *suggestion*
  input, never an authorization input — this is the core rule the phase
  exists to enforce, not a threshold to eventually lower.
- **No new consent/confirmation mechanism for actions ADR 0011 already
  covers** (email send, calendar writes). This phase adds a command gate
  for actions that currently lack any structured gate; it does not
  redesign the existing text-only confirmation flow.
- **No command-line-style flags/options parsing complexity in v1.** Initial
  commands are fixed-shape (`/reachy <action>` [`<argument>`]), not a
  general argument grammar.
- **No retroactive relaxation of the named-behaviour-playback exception.**
  Bounded pre-recorded moves keep their existing natural-language-eligible
  status; this phase does not add or remove members of that class.

## Implementation implications

The existing substring-based `is_standby_command`/`is_resume_command` in
`companion_core/robot_power_intent.py` is superseded, not patched: the fix
here is not a better negation-aware regex (still fragile against
quotation, sarcasm, and novel phrasing — the "increasingly complex
keyword/regex matcher" trap this phase explicitly rejects), but removing
this module's authority to actuate at all. **The module itself is retired,
not repurposed** — reusing its substring matcher as the suggestion
classifier would preserve the exact semantic false-positive it caused,
just downgraded from actuation to a wrong suggestion (e.g. "How do I turn
off Reachy?" would still produce "It sounds like you want to put Reachy
into standby" instead of the plain answer the interaction-tiers table
requires). The natural-language suggestion classifier is a separate,
new implementation — capable of distinguishing requests from questions,
negations, hypotheticals and quoted/reported speech via the
`speech_act` field described above — not a demoted version of the retired
matcher. Its phrase lists may inform that classifier's examples/prompt
cues, but must not themselves determine suggestion intent. Only
`/reachy standby`/`wake` (or their registered aliases — see Channel
handling) parsed by the new command parser may call the actual
`POST /robots/standby`/`resume` path going forward.

## Implementation sequence

1. Add `companion_core/commands/` — the deterministic slash-command parser
   (`namespace`, `action`, optional argument) and the `Command` type,
   evaluated before both the existing `*_intent.py` chain and the generic
   LLM branch in `app.py`, mirroring the precedence
   `robot_power_intent` already occupies.
2. Wire `/reachy standby`, `/reachy wake`, `/reachy status` (and their
   Telegram aliases `/standby`, `/wake`, `/reachy_status`) through the
   parser to the existing `POST /robots/standby`/`resume` hub calls
   (unchanged endpoints/authorization — only the trigger path changes).
3. Retire `robot_power_intent`'s substring matching entirely (no
   authoritative or suggestion role); add the separate natural-language
   suggestion classifier with its fixed-schema output (`intent`,
   `speech_act`, `confidence`, per Required behaviour), treating any
   timeout, malformed/non-schema response, or missing/unrecognized
   `speech_act`/`confidence` as "no suggestion" rather than a fallback
   guess; wire it to format a suggested-command reply only when
   `speech_act == "request"` and confidence clears threshold.
4. Add the interactive-control (button) suggestion path for channels that
   support it (web chat first; Telegram inline keyboards as a fast-follow),
   dispatching the same structured `Command` on press.
5. Register the flat aliases `/standby`, `/wake`, `/reachy_status` in
   Telegram's bot command menu via its existing bot-command-list API
   (Telegram's `BotCommand.command` cannot contain a space, so the
   namespaced `/reachy <action>` form cannot be registered there directly
   — see Channel handling).
6. Extend the web chat UI with command autocomplete for the namespaced
   `/reachy <action>` form.
7. Audit other existing natural-language-triggered consequential paths for
   the same class of false positive and bring any found under the same
   command-parser gate (scoped at implementation time — this plan does not
   enumerate beyond `robot_power_intent`, the confirmed instance).

## Exit criteria

| Check | Required result |
|---|---|
| Negative conversational examples never actuate or suggest | None of "How do I turn off Reachy?", "Don't turn off Reachy.", "I don't want to turn off Reachy.", "Can you explain how to turn off Reachy?", "What happens if I turn off Reachy?", "Is it safe to turn off Reachy?", "How do I wake up Reachy?", "Don't wake up Reachy." calls `POST /robots/standby`/`resume` **or** produces a suggested-command reply/button — the classifier must resolve each to a non-`request` `speech_act`, not merely fail to actuate |
| Explicit commands still work | `/reachy standby` and `/reachy wake` (and their Telegram aliases) call the existing standby/resume path exactly as `robot_power_intent`'s matched phrases do today, through the new parser |
| Suggestion, not action | A `speech_act == "request"` natural-language match ("Could you put Reachy to sleep?") produces a suggested-command reply or action-button render and does not itself call the standby/resume path |
| Button dispatch | Pressing a rendered action button dispatches the same structured `Command` the slash form would, and is itself the authorization event, not the sentence that produced the button |
| Alias equivalence | `/standby` (Telegram-registered alias) and `/reachy standby` (namespaced form) parse to the identical structured `Command` and produce identical authorization/action results |
| Classifier fail-closed | A forced classifier timeout, malformed/non-schema response, or a response missing/misvaluing `speech_act`/`confidence` produces no suggestion and no error surfaced to the user; the ordinary conversational reply is returned unchanged, verified by call-count/output assertions, not by inspecting classifier internals |
| Channel parity | The same command text produces identical parsing/authorization/action results whether it arrives via Telegram or web chat |
| Scope preserved | Named-behaviour playback and ADR 0011's existing email/calendar consent flows are unaffected — neither gains nor loses their current authorization requirements |
| Regression | Existing Python/Ruff/browser checks and Phase 22b's standby/resume tests still pass under the new trigger path |

Implemented 2026-09-24 (companion-core: `commands/`, `command_suggestion.py`;
reachy-hub: Telegram `setMyCommands` registration; operator UI: command
autocomplete and suggested-command action buttons), verified with isolated
fixtures per the exit-criteria table above. No live Telegram bot run or
physical robot actuation was performed this session.
