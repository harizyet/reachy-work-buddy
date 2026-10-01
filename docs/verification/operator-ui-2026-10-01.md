# Operator UI reorganization — 2026-10-01

Implemented locally; not deployed. The [operator guide](../operator-guide.md)
owns navigation and behavior; [ADR 0017](../adr/0017-web-chat-channel.md#saved-web-records-amendment-2026-10-01)
owns the saved-record boundary. Deployment needs the additive `012_web_chats`
migration and rebuilt hub/core/migration images, following the
[existing upgrade procedure](../deployment.md#schema-upgrades-and-credential-keys).

## Evidence

- Real Chromium against local HTTP fixtures: all 10 browser tests passed.
  Direct `/ui/` and proxied `/hub/ui/` paths, desktop/mobile widths, settings
  keyboard navigation and draft retention, saved-chat reopen after refresh,
  literal rendering, no browser storage, login expiry, late replies, meeting
  search and out-of-order detail responses were exercised. Existing account,
  search, animation and robot voice controls passed their fixture tests.
- The workspace browser test was then extended and passed again with Chromium's
  fake microphone device: selecting a meeting stops browser recording and
  retains the clip in Add meeting. No physical microphone or robot was used.
- `services/reachy-hub/tests/test_operator.py`: 18 passed, including an actual
  in-process hub/core chain for saved turns, shared session IDs, cookie/CSRF,
  bearer access, owner binding, logout, cross-user record lookup and uncertain
  failures. These are fixture/in-process checks, not real model invocation.
- Real Postgres (`pgvector/pgvector:pg16`) in disposable Compose project
  `reachy-ui-check`: migration suite 19 passed, 1 skipped. Included schema/data
  preservation checks and saving/reading web records after closing and
  reconnecting the SQL store. The container-based backup/restore test was
  skipped because its separate opt-in container variable was not set.
  The temporary project used tmpfs data and was removed afterward.
- Broad hub suite excluding slow tests: 350 passed, 3 skipped, 9 deselected,
  1 failed. `test_spoken_command_text_does_not_actuate_the_robot` expects both
  scripted voice replies to contain `turn`; that assertion also fails with
  the original HEAD hub `app.py` in a separate temporary source copy. It is
  not introduced by the UI/archive changes and remains unresolved.
- Repository Ruff, changed JavaScript syntax, whitespace and documentation
  link/anchor checks passed. Desktop screenshots were inspected; mobile layout
  bounds and interactions were checked in Chromium.

## Limits

No live services were redeployed, no production database was migrated, and no
real model, Telegram account, inference sidecar or robot was invoked. Meeting
transcription/diarization acceptance is unchanged. Saved web records preserve
presentation history only; the assistant still has one shared cross-channel
session and bounded in-memory reasoning context. Old unsaved messages and live
robot voice turns are not backfilled into the archive.
