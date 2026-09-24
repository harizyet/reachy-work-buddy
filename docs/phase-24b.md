# Phase 24b — Structured command and intent authorization

Status: planned, not implemented. One of two independent tracks under
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

- **Explicit commands** use a namespaced slash-command syntax, parsed
  deterministically before both the existing deterministic-intent chain and
  the generic LLM conversation branch — same precedence position
  `robot_power_intent` already occupies today, just replacing substring
  matching with an unambiguous parser. Recommended initial form:

  ```text
  /reachy standby
  /reachy wake
  /reachy status
  /reachy gesture greeting
  ```

  A flatter form (`/standby`, `/wake`) may also be accepted, but the
  namespaced form is preferred as the primary/documented one — it scales to
  future assistant commands (search, persona, settings) without a
  collision, where a flat global command namespace eventually would.
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
  authoritative.** The existing local-LLM/deterministic-intent machinery
  may still classify free-form text (e.g. "Could you put Reachy to sleep?"
  → `{"intent": "robot_standby", "confidence": 0.97}`), but a recognized
  intent triggers a *suggestion*, never the action itself:

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
  autocomplete); `/reachy standby`, `/reachy wake`, `/reachy status` map
  directly onto it and should be registered in Telegram's command menu via
  its existing bot-command-list API.
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
`companion_core/robot_power_intent.py` is superseded, not patched: the
fix here is not a better negation-aware regex (still fragile against
quotation, sarcasm, and novel phrasing — the "increasingly complex
keyword/regex matcher" trap this phase explicitly rejects), but removing
this module's authority to actuate at all. Its phrase lists become the
seed vocabulary for the natural-language *suggestion* classifier instead;
only `/reachy standby` and `/reachy wake` (parsed by the new command
parser) may call the actual `POST /robots/standby`/`resume` path going
forward.

## Implementation sequence

1. Add `companion_core/commands/` — the deterministic slash-command parser
   (`namespace`, `action`, optional argument) and the `Command` type,
   evaluated before both the existing `*_intent.py` chain and the generic
   LLM branch in `app.py`, mirroring the precedence
   `robot_power_intent` already occupies.
2. Wire `/reachy standby`, `/reachy wake`, `/reachy status` through the
   parser to the existing `POST /robots/standby`/`resume` hub calls
   (unchanged endpoints/authorization — only the trigger path changes).
3. Demote `robot_power_intent`'s phrase lists to a non-authoritative
   suggestion classifier: on a match, format a suggested-command reply
   (text) instead of calling the standby/resume path directly.
4. Add the interactive-control (button) suggestion path for channels that
   support it (web chat first; Telegram inline keyboards as a fast-follow),
   dispatching the same structured `Command` on press.
5. Register `/reachy standby`, `/reachy wake`, `/reachy status` in
   Telegram's bot command menu via its existing API.
6. Extend the web chat UI with command autocomplete for the registered
   command set.
7. Audit other existing natural-language-triggered consequential paths for
   the same class of false positive and bring any found under the same
   command-parser gate (scoped at implementation time — this plan does not
   enumerate beyond `robot_power_intent`, the confirmed instance).

## Exit criteria

| Check | Required result |
|---|---|
| Negative conversational examples never actuate | None of "How do I turn off Reachy?", "Don't turn off Reachy.", "I don't want to turn off Reachy.", "Can you explain how to turn off Reachy?", "What happens if I turn off Reachy?", "Is it safe to turn off Reachy?", "How do I wake up Reachy?", "Don't wake up Reachy." calls `POST /robots/standby`/`resume`, verified by call-count assertions |
| Explicit commands still work | `/reachy standby` and `/reachy wake` call the existing standby/resume path exactly as `robot_power_intent`'s matched phrases do today, through the new parser |
| Suggestion, not action | A high-confidence natural-language match ("Could you put Reachy to sleep?") produces a suggested-command reply or action-button render and does not itself call the standby/resume path |
| Button dispatch | Pressing a rendered action button dispatches the same structured `Command` the slash form would, and is itself the authorization event, not the sentence that produced the button |
| Channel parity | The same command text produces identical parsing/authorization/action results whether it arrives via Telegram or web chat |
| Scope preserved | Named-behaviour playback and ADR 0011's existing email/calendar consent flows are unaffected — neither gains nor loses their current authorization requirements |
| Regression | Existing Python/Ruff/browser checks and Phase 22b's standby/resume tests still pass under the new trigger path |

No implementation, live robot actuation, or Telegram/web UI change is
performed by this planning change.
