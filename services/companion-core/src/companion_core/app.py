"""companion-core: reasoning/tools/memory service.

Phase 4: minimal service proving companion-core -> reachy-hub ->
reachy-embodiment end to end. The `/debug/*` routes are a stand-in for what
will eventually be an agent tool call — not the tool-calling framework
itself.

Phase 5: POST /conversation is the real, stable contract reachy-hub calls
per turn (ADR 0002) — companion-core receives only a session_id,
conversation_id, channel label, and text, never "this came from Telegram"
as anything but an opaque string. The reasoning inside is a placeholder
(echoes turn count) until Phase 10+ replaces it with a real agent.

Phase 9: the response now carries real (if simplistic) `Privacy`/`Urgency`
metadata (privacy_classifier.py) — companion-core *proposes* this per
docs/plan.md §4 ("the LLM may propose metadata"); reachy-hub's response
router (Phase 9, ADR 0006) has final, enforced authority over what actually
happens with it.

Phase 10: calendar, per docs/plan.md's Phase 10 row ("Read-only
next/list/free-busy first; later writes behind confirmation") — see
calendar/. companion-core owns a real database connection for the first
time (previously entirely stateless beyond the in-memory conversation
transcript); no external calendar credential was available, so the
concrete `CalendarStore` is a local Postgres-backed one (calendar/
postgres_store.py), matching the graceful-degradation-without-credentials
pattern used for Telegram/TTS. `is_next_event_query` (calendar_intent.py)
is a placeholder keyword matcher (same honesty-about-scope as
privacy_classifier.py) that answers "what's next" using real stored
calendar data — Phase 10's exit criterion is that the *answer* is real,
not that the question-understanding is sophisticated.

Phase 11: tasks/notes/reminders, per docs/plan.md's Phase 11 row ("Capture,
list, complete and search basic work items") — see tasks/. Unlike
calendar, capturing a task *is* the agent action this phase is about
("Agent can record... explicit follow-ups"): `POST /conversation`
recognizes capture/list/complete/search phrasings (task_intent.py, same
placeholder-matcher honesty as calendar_intent.py) and calls `TaskStore`
directly — no separate admin/confirmation gate, since recording a task is
low-stakes and easily undoable (docs/plan.md §9's permission tiers), unlike
a calendar write (still admin-only, ADR 0010) or an email send (Phase 14).

Phase 12: work memory, per docs/plan.md's Phase 12 row ("Profile, working
and episodic memory with provenance, sensitivity and expiry") — see
memory/. `MemoryRecord` (shared/models/memory.py) has existed as a
forward-looking data contract since Phase 0; this phase is the first real
implementation against it. `POST /conversation` recognizes "remember that
X" (memory_intent.py, same placeholder-matcher pattern as calendar/task
intent) and stores it via `MemoryStore.add_memory` directly — memory
capture is the same kind of low-stakes, no-confirmation-needed agent action
task capture (Phase 11) is, not calendar's read-only-to-the-agent design.
"Do you remember X" recalls by content search against `MemoryStore` —
never against `conversation.py`'s per-session transcript — which is the
literal mechanism behind the exit criterion, "Stored work fact can be
recalled later without transcript dumping."

Phase 13: RAG, per docs/plan.md's Phase 13 row ("Document ingestion,
embeddings/vector store, provenance-aware retrieval") — see rag/. No cloud
embeddings key was available, so `rag/embeddings.py` embeds locally with a
small sentence-transformers model, same graceful-degradation pattern as
Phase 8's local STT/TTS; the vector store is Postgres + pgvector
(`rag/postgres_store.py`), per docs/plan.md §8. `POST /conversation`
recognizes doc-lookup phrasings (rag_intent.py, same placeholder-matcher
pattern as calendar/task/memory intent) and answers from
`DocumentStore.search` results. The exit criterion ("Answers identify
their supporting document/section/page where available") is
`rag_intent.format_answer`'s job: it always names the source document, and
the section too when the retrieved chunk has one — there's no `page`,
since nothing here ingests PDFs.

Phase 14: email, per docs/plan.md's Phase 14 row ("Read/summarize/draft/
preview/approve/send") — see email/. No external email credential was
available, so "read" means listing seeded `EmailMessage`s (`POST
/emails/received`, operator/setup API, same no-external-sync honesty as
calendar), and "summarize" is out of scope until there's a real LLM in this
codebase (same as "draft" below) — not attempted, not faked. `POST
/conversation` recognizes draft/approve/send phrasings (email_intent.py,
same placeholder-matcher honesty as the other *_intent.py modules); a
draft's body is the user's text verbatim, the same way "remember that X"
stores X verbatim. The exit criterion ("No code path sends mail without
approval gate") is a structural property, not a claim: `email/workflow.py`'s
`send_approved_draft` is the *only* function anywhere in this codebase
that calls an `EmailSender`, both from `POST /emails/drafts/{id}/send` and
the conversational "send draft X" path, and it always checks
`DraftStatus.APPROVED` first. No cloud email API key was available either,
so the real sender (`email/sender.py`) speaks plain SMTP directly — in the
homelab compose stack, to a local Mailpit container, not a real mailbox.

ADR 0011 (destructive-action consent, a cross-cutting safety refactor
inserted ahead of Phase 15, not itself a numbered phase): two hard rules,
enforced structurally by consent/gate.py, not left to whatever reasoning
eventually replaces the placeholder matchers here. (1) A destructive
action can never be requested at bulk/mass scope — `request_confirmation`
refuses before a row even exists, so "delete the whole mailbox" has no
path to confirmation, confirmed or not. (2) A destructive-action
confirmation can never come from voice — `confirm_action`/`require_text`
refuse it regardless of what the audio transcribes to; `ConversationTurnRequest.
input_modality` (only ever VOICE from `/voice/turn`, via reachy-hub) is
how that signal survives the trip from audio to here. Memory's forget is
now this codebase's first real user of the gate: "forget X" only
*requests* a confirmation (`memory.forget`, SINGLE scope), "yes forget X"
confirms it, and forgetting is a soft delete (`MemoryRecord.forgotten_at`)
so "restore X" can always undo it — "any action performed should always
be able to be undone" is architecture here, not a promise. Email's
approve/send-trigger both now require text too, and "send draft X" no
longer dispatches immediately: it queues a real send ~10 minutes out
(`email/workflow.py`'s `queue_draft_for_sending`), during which
"cancel send X" (any modality — undo is always allowed) reverts it; a
background loop (`run_dispatch_loop`) is what actually calls the
`EmailSender`, and only for what's due.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from companion_core import email_intent, memory_intent, rag_intent
from companion_core.briefing import BriefingItem, build_briefing
from companion_core.calendar.models import CalendarEvent
from companion_core.calendar.postgres_store import PostgresCalendarStore
from companion_core.calendar.reminders import due_reminders, reminder_urgency
from companion_core.calendar.store import CalendarStore
from companion_core.calendar_intent import format_next_event_reply, is_next_event_query
from companion_core.consent.gate import (
    ConfirmationExpiredError,
    ConfirmationNotFoundError,
    VoiceConfirmationNotAllowedError,
    confirm_action,
    request_confirmation,
    require_text,
)
from companion_core.consent.models import ActionScope, ConfirmationRequest
from companion_core.consent.postgres_store import PostgresConfirmationStore
from companion_core.consent.store import ConfirmationStore
from companion_core.conversation import ConversationStore
from companion_core.email.models import DraftStatus, EmailDraft, EmailMessage
from companion_core.email.postgres_store import PostgresEmailStore
from companion_core.email.sender import smtp_send
from companion_core.email.store import EmailStore
from companion_core.email.workflow import (
    DEFAULT_SEND_DELAY_SECONDS,
    DraftNotApprovedError,
    DraftNotQueuedError,
    SendFn,
    cancel_queued_draft,
    queue_draft_for_sending,
    run_dispatch_loop,
)
from companion_core.hub_client import HubClient
from companion_core.llm.client import OpenAICompatibleChatProvider, ProviderUnavailable
from companion_core.llm.postgres_store import (
    PostgresLLMSettingsStore,
    PostgresLLMUsageStore,
)
from companion_core.llm.store import LLMSettingsStore, LLMUsageStore, masked_config
from companion_core.memory.postgres_store import PostgresMemoryStore
from companion_core.memory.store import MemoryStore
from companion_core.privacy_classifier import classify_privacy
from companion_core.rag.postgres_store import PostgresDocumentStore
from companion_core.rag.store import DocumentStore
from companion_core.task_intent import (
    format_capture_reply,
    format_complete_reply,
    format_list_reply,
    format_search_reply,
    is_list_query,
    match_capture,
    match_complete,
    match_search,
)
from companion_core.tasks.models import Task, TaskStatus
from companion_core.tasks.postgres_store import PostgresTaskStore
from companion_core.tasks.store import TaskStore
from shared.models.llm import LLMConfigPatch
from shared.models.memory import MemoryRecord, MemoryType
from shared.models.rag import DocumentChunk, RetrievedChunk
from shared.models.response import Privacy, Urgency
from shared.models.session import InputModality
from shared.protocols.operator_api import LLM_SETTINGS, LLM_USAGE


class ConversationTurnRequest(BaseModel):
    session_id: str
    conversation_id: str
    channel: str
    text: str
    input_modality: InputModality = InputModality.TEXT


class ConversationTurnResponse(BaseModel):
    reply: str
    turn_count: int
    privacy: Privacy


class ReminderPayload(BaseModel):
    event_id: str
    text: str
    privacy: Privacy
    urgency: Urgency


class CreateTaskRequest(BaseModel):
    text: str


class ConfirmForgetRequest(BaseModel):
    confirmation_id: str


class CreateMemoryRequest(BaseModel):
    content: str
    type: MemoryType = MemoryType.WORKING
    project_scope: str | None = None
    confidence: float = 1.0
    sensitivity: Privacy | None = None
    expires_at: datetime | None = None


class CreateDocumentRequest(BaseModel):
    title: str
    content: str
    source: str = "api"


class ReceiveEmailRequest(BaseModel):
    sender: str
    subject: str
    body: str


class CreateDraftRequest(BaseModel):
    to: str
    subject: str
    body: str
    in_reply_to: str | None = None


def create_app(
    *,
    llm_settings_store: LLMSettingsStore | None = None,
    llm_usage_store: LLMUsageStore | None = None,
    llm_transport: httpx.AsyncBaseTransport | None = None,
    hub_base_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    calendar_store: CalendarStore | None = None,
    task_store: TaskStore | None = None,
    memory_store: MemoryStore | None = None,
    rag_store: DocumentStore | None = None,
    email_store: EmailStore | None = None,
    email_send_fn: SendFn = smtp_send,
    email_send_delay_seconds: int | None = None,
    confirmation_store: ConfirmationStore | None = None,
    database_url: str | None = None,
    run_email_dispatch_task: bool = True,
    email_dispatch_interval: float | None = None,
    hub_bearer_token: str | None = None,
) -> FastAPI:
    hub_base_url = hub_base_url or os.environ.get("REACHY_HUB_URL", "http://reachy-hub:8000")
    # Both env-overridable, same pattern as hub_base_url above — default
    # stays the real ~10 minutes (ADR 0011), but a deployment (e.g. a
    # staging/test compose override) can shorten both the delay and how
    # often the dispatch loop checks for due drafts, without a code change.
    # `or None` on the env lookups: docker-compose's `${VAR:-}` substitutes
    # an empty string, not an unset variable, when VAR isn't set in .env —
    # `int("")` would otherwise raise instead of falling through to the
    # default.
    if email_send_delay_seconds is None:
        email_send_delay_seconds = int(os.environ.get("EMAIL_SEND_DELAY_SECONDS") or DEFAULT_SEND_DELAY_SECONDS)
    if email_dispatch_interval is None:
        email_dispatch_interval = float(os.environ.get("EMAIL_DISPATCH_INTERVAL_SECONDS") or 30.0)
    conversation_store = ConversationStore()
    owns_llm_settings = llm_settings_store is None
    owns_llm_usage = llm_usage_store is None
    owns_calendar_store = calendar_store is None
    owns_task_store = task_store is None
    owns_memory_store = memory_store is None
    owns_rag_store = rag_store is None
    owns_email_store = email_store is None
    owns_confirmation_store = confirmation_store is None

    # Phase 16/ADR 0013: reachy-hub's REMOTE_UI_TOKEN, shared with this
    # internal caller — see hub_client.py's constructor comment. `or None`
    # for the same docker-compose `${VAR:-}` reason as the email env
    # lookups above.
    hub_bearer_token = hub_bearer_token or os.environ.get("REMOTE_UI_TOKEN") or None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.hub_client = HubClient(hub_base_url, transport=transport, bearer_token=hub_bearer_token)
        if owns_llm_settings:
            app.state.llm_settings_store = await PostgresLLMSettingsStore.connect(database_url or os.environ["DATABASE_URL"])
        if owns_llm_usage:
            app.state.llm_usage_store = await PostgresLLMUsageStore.connect(database_url or os.environ["DATABASE_URL"])
        if owns_calendar_store:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.calendar_store = await PostgresCalendarStore.connect(dsn)
        if owns_task_store:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.task_store = await PostgresTaskStore.connect(dsn)
        if owns_memory_store:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.memory_store = await PostgresMemoryStore.connect(dsn)
        if owns_rag_store:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.rag_store = await PostgresDocumentStore.connect(dsn)
        if owns_email_store:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.email_store = await PostgresEmailStore.connect(dsn)
        if owns_confirmation_store:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.confirmation_store = await PostgresConfirmationStore.connect(dsn)

        # Only actually dispatches drafts whose dispatch_at has passed —
        # queueing a draft doesn't send it, this loop noticing it's due
        # does. Same real-background-task pattern as reachy-hub's
        # heartbeat_loop.
        dispatch_task = (
            asyncio.create_task(
                run_dispatch_loop(app.state.email_store, send_fn=email_send_fn, interval_seconds=email_dispatch_interval)
            )
            if run_email_dispatch_task
            else None
        )
        try:
            yield
        finally:
            if dispatch_task is not None:
                dispatch_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await dispatch_task
            await app.state.hub_client.aclose()
            if owns_llm_settings:
                await app.state.llm_settings_store.close()
            if owns_llm_usage:
                await app.state.llm_usage_store.close()
            if owns_calendar_store:
                await app.state.calendar_store.close()
            if owns_task_store:
                await app.state.task_store.close()
            if owns_memory_store:
                await app.state.memory_store.close()
            if owns_rag_store:
                await app.state.rag_store.close()
            if owns_email_store:
                await app.state.email_store.close()
            if owns_confirmation_store:
                await app.state.confirmation_store.close()

    app = FastAPI(title="companion-core", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(request, exc):
        if request.url.path in (LLM_SETTINGS,):
            return JSONResponse(status_code=422, content={"detail": "Invalid request fields"})
        return await request_validation_exception_handler(request, exc)

    app.state.conversation_store = conversation_store
    if llm_settings_store is not None:
        app.state.llm_settings_store = llm_settings_store
    if llm_usage_store is not None:
        app.state.llm_usage_store = llm_usage_store

    @app.get(LLM_SETTINGS)
    async def get_llm_settings() -> dict:
        return masked_config(await app.state.llm_settings_store.get())

    @app.put(LLM_SETTINGS)
    async def set_llm_settings(patch: LLMConfigPatch) -> dict:
        try:
            return masked_config(await app.state.llm_settings_store.set(patch))
        except ValidationError:
            # Validation errors include input values by default, potentially secrets.
            raise HTTPException(422, "Invalid provider settings; supply a model and HTTP(S) base URL") from None

    @app.get(LLM_USAGE)
    async def get_llm_usage(limit: int = Query(50, ge=1, le=500),
                            since_hours: int = Query(24, ge=1, le=8760)) -> dict:
        store = app.state.llm_usage_store
        return {"entries": [e.model_dump(mode="json") for e in await store.list_recent(limit)],
                **await store.summary(datetime.now(UTC) - timedelta(hours=since_hours))}

    if not owns_calendar_store:
        app.state.calendar_store = calendar_store
    if not owns_task_store:
        app.state.task_store = task_store
    if not owns_memory_store:
        app.state.memory_store = memory_store
    if not owns_rag_store:
        app.state.rag_store = rag_store
    if not owns_email_store:
        app.state.email_store = email_store
    if not owns_confirmation_store:
        app.state.confirmation_store = confirmation_store

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/conversation")
    async def conversation_turn(turn: ConversationTurnRequest) -> ConversationTurnResponse:
        async with conversation_store.turn_lock(turn.session_id):
            return await process_conversation_turn(turn)

    async def process_conversation_turn(turn: ConversationTurnRequest) -> ConversationTurnResponse:
        history = conversation_store.append(turn.session_id, turn.channel, turn.text)

        capture_text = match_capture(turn.text)
        complete_query = match_complete(turn.text)
        search_query = match_search(turn.text)
        memory_capture_text = memory_intent.match_capture(turn.text)
        memory_recall_query = memory_intent.match_recall(turn.text)
        confirm_forget_query = memory_intent.match_confirm_forget(turn.text)
        forget_query = memory_intent.match_forget(turn.text)
        restore_query = memory_intent.match_restore(turn.text)
        rag_query = rag_intent.match_query(turn.text)
        draft_request = email_intent.match_draft(turn.text)
        approve_query = email_intent.match_approve(turn.text)
        cancel_send_query = email_intent.match_cancel_send(turn.text)
        send_query = email_intent.match_send(turn.text)

        if is_next_event_query(turn.text):
            event = await app.state.calendar_store.next_event(datetime.now(UTC))
            reply = format_next_event_reply(event)
            # Calendar content is inherently work-private (docs/plan.md §4's
            # routing table) regardless of whether the query text itself
            # happens to contain a privacy keyword — we know for certain
            # this reply reveals schedule details, so this isn't inferred
            # from turn.text the way the generic placeholder reply is.
            privacy = Privacy.WORK_PRIVATE
        elif capture_text:
            task = await app.state.task_store.add_task(capture_text)
            reply = format_capture_reply(task)
            privacy = classify_privacy(turn.text)
        elif complete_query:
            open_tasks = await app.state.task_store.list_tasks(TaskStatus.OPEN)
            matched = next((t for t in open_tasks if complete_query.lower() in t.text.lower()), None)
            completed = await app.state.task_store.complete_task(matched.id) if matched else None
            reply = format_complete_reply(completed, complete_query)
            privacy = classify_privacy(turn.text)
        elif search_query:
            found = await app.state.task_store.search_tasks(search_query)
            reply = format_search_reply(found, search_query)
            privacy = classify_privacy(turn.text)
        elif is_list_query(turn.text):
            open_tasks = await app.state.task_store.list_tasks(TaskStatus.OPEN)
            reply = format_list_reply(open_tasks)
            privacy = classify_privacy(turn.text)
        elif memory_capture_text:
            record = await app.state.memory_store.add_memory(
                content=memory_capture_text,
                source="conversation",
                sensitivity=classify_privacy(memory_capture_text),
            )
            reply = memory_intent.format_capture_reply(record)
            privacy = record.sensitivity
        elif memory_recall_query:
            # Deliberately queries MemoryStore only — never conversation_store
            # — this is the exit criterion's "without transcript dumping" as
            # an actual code-level guarantee, not just a claim.
            found = await app.state.memory_store.recall(memory_recall_query)
            reply = memory_intent.format_recall_reply(found, memory_recall_query)
            privacy = memory_intent.most_restrictive_privacy(found, default=classify_privacy(turn.text))
        elif confirm_forget_query:
            # docs/adr/0011: the only place memory.forget is actually
            # invoked, and only after confirm_action has verified this
            # wasn't a voice-sourced attempt.
            pending = await app.state.confirmation_store.find_pending("memory.forget", confirm_forget_query)
            if pending is None:
                reply = memory_intent.format_confirmation_not_found_reply(confirm_forget_query)
            else:
                try:
                    confirmed = await confirm_action(
                        app.state.confirmation_store, pending.id, input_modality=turn.input_modality
                    )
                    record = await app.state.memory_store.forget(confirmed.target_id)
                    reply = (
                        memory_intent.format_forgotten_reply(record)
                        if record
                        else memory_intent.format_confirmation_not_found_reply(confirm_forget_query)
                    )
                except VoiceConfirmationNotAllowedError:
                    reply = memory_intent.format_voice_confirmation_blocked_reply()
                except (ConfirmationNotFoundError, ConfirmationExpiredError):
                    reply = memory_intent.format_confirmation_not_found_reply(confirm_forget_query)
            privacy = Privacy.WORK_PRIVATE
        elif forget_query:
            # Only *requests* a confirmation — never deletes anything
            # itself. request_confirmation is always called at SINGLE
            # scope here (one recalled record); it would refuse BULK
            # outright if anything ever asked for that (docs/adr/0011).
            found = await app.state.memory_store.recall(forget_query)
            if not found:
                reply = memory_intent.format_forget_not_found_reply(forget_query)
            else:
                target = found[0]
                await request_confirmation(
                    app.state.confirmation_store,
                    action_type="memory.forget",
                    target_id=target.id,
                    description=target.content,
                    scope=ActionScope.SINGLE,
                )
                reply = memory_intent.format_forget_confirmation_reply(target, forget_query)
            privacy = Privacy.WORK_PRIVATE
        elif restore_query:
            # The undo — no confirmation gate, any modality: undoing must
            # never be harder than the destructive action it reverses.
            found = await app.state.memory_store.find_forgotten(restore_query)
            if not found:
                reply = memory_intent.format_restore_not_found_reply(restore_query)
            else:
                restored = await app.state.memory_store.restore(found[0].id)
                reply = memory_intent.format_restored_reply(restored)
            privacy = Privacy.WORK_PRIVATE
        elif rag_query:
            results = await app.state.rag_store.search(rag_query)
            reply = rag_intent.format_answer(results, rag_query)
            privacy = classify_privacy(reply)
        elif email_intent.match_list_inbox(turn.text):
            messages = await app.state.email_store.list_received()
            reply = email_intent.format_inbox_reply(messages)
            privacy = Privacy.WORK_PRIVATE
        elif draft_request:
            to, body = draft_request
            draft = await app.state.email_store.create_draft(to=to, subject=body, body=body)
            reply = email_intent.format_draft_reply(draft)
            privacy = Privacy.WORK_PRIVATE
        elif approve_query:
            # docs/adr/0011: approval is consent for an outbound
            # communication — text-only, same rule as memory.forget's
            # confirmation.
            try:
                require_text(turn.input_modality)
                pending = await app.state.email_store.list_drafts(DraftStatus.DRAFT)
                matched = email_intent.find_draft_by_query(pending, approve_query)
                approved = await app.state.email_store.approve_draft(matched.id) if matched else None
                reply = email_intent.format_approve_reply(approved, approve_query)
            except VoiceConfirmationNotAllowedError:
                reply = memory_intent.format_voice_confirmation_blocked_reply()
            privacy = Privacy.WORK_PRIVATE
        elif cancel_send_query:
            # The undo — no text-only gate: cancelling is always safe and
            # must never be harder than the send it's cancelling.
            candidates = await app.state.email_store.list_drafts(DraftStatus.QUEUED)
            matched = email_intent.find_draft_by_query(candidates, cancel_send_query)
            if matched is None:
                reply = email_intent.format_send_not_found_reply(cancel_send_query)
            else:
                cancelled = await cancel_queued_draft(app.state.email_store, matched.id)
                reply = email_intent.format_cancel_send_reply(cancelled)
            privacy = Privacy.WORK_PRIVATE
        elif send_query:
            # "send draft X" only *queues* it ~10 minutes out — docs/adr/0011's
            # delay-before-dispatch window — and requires text, same as
            # approval. run_dispatch_loop (started in lifespan) is what
            # actually calls email_send_fn later, once due.
            try:
                require_text(turn.input_modality)
                candidates = await app.state.email_store.list_drafts()
                matched = email_intent.find_draft_by_query(candidates, send_query)
                if matched is None:
                    reply = email_intent.format_send_not_found_reply(send_query)
                else:
                    try:
                        queued = await queue_draft_for_sending(
                            app.state.email_store, matched.id, delay_seconds=email_send_delay_seconds
                        )
                        reply = email_intent.format_send_queued_reply(queued, email_send_delay_seconds)
                    except DraftNotApprovedError:
                        reply = email_intent.format_send_not_approved_reply(matched)
            except VoiceConfirmationNotAllowedError:
                reply = memory_intent.format_voice_confirmation_blocked_reply()
            privacy = Privacy.WORK_PRIVATE
        else:
            config = await app.state.llm_settings_store.get()
            if config.local is None:
                reply = f"(turn {len(history)} via {turn.channel}) heard: {turn.text}"
            else:
                provider = OpenAICompatibleChatProvider(config.local, app.state.llm_usage_store, transport=llm_transport)
                try:
                    reply = await provider.complete(conversation_store.messages(turn.session_id))
                except ProviderUnavailable:
                    reply = "The language model is unavailable right now. Please try again shortly."
            privacy = classify_privacy(turn.text)
            if config.local is not None:
                privacy = conversation_store.reply_privacy(turn.session_id, classify_privacy(turn.text + "\n" + reply))

        conversation_store.record_reply(turn.session_id, reply, privacy)
        return ConversationTurnResponse(reply=reply, turn_count=len(history), privacy=privacy)

    @app.post("/calendar/events")
    async def add_calendar_event(event: CalendarEvent) -> CalendarEvent:
        """Operator/setup API, not an agent tool: with no external calendar
        sync in this V0.1 default, this is how events get into the store at
        all. The agent's own access is read-only (next_event et al.)."""
        return await app.state.calendar_store.add_event(event)

    @app.get("/calendar/events")
    async def list_calendar_events(start: datetime, end: datetime) -> list[CalendarEvent]:
        return await app.state.calendar_store.list_events(start, end)

    @app.get("/calendar/next")
    async def next_calendar_event() -> CalendarEvent | None:
        return await app.state.calendar_store.next_event(datetime.now(UTC))

    @app.get("/calendar/free-busy")
    async def free_busy(start: datetime, end: datetime) -> list[dict[str, datetime]]:
        # Free/busy intentionally reveals only time blocks, not what's in
        # them — a different (narrower) privacy surface than /calendar/events.
        events = await app.state.calendar_store.list_events(start, end)
        return [{"start": event.start, "end": event.end} for event in events]

    @app.get("/calendar/reminders/due")
    async def reminders_due(within_minutes: int = 15) -> list[ReminderPayload]:
        now = datetime.now(UTC)
        events = await due_reminders(app.state.calendar_store, now, within_minutes)
        return [
            ReminderPayload(
                event_id=event.id,
                text=f"Reminder: '{event.title}' starts at {event.start.strftime('%H:%M')}.",
                privacy=Privacy.WORK_PRIVATE,
                # Phase 17 (docs/adr/0014): graded, not hardcoded — reachy-hub's
                # interruption engine needs a real distinction between "starting
                # imminently" and "just came into the reminder window" to ever
                # demonstrate routine-notification deferral with real calendar
                # data. 5 minutes chosen to match this endpoint's own
                # within_minutes default (15) leaving room for a NORMAL band.
                urgency=reminder_urgency(event, now),
            )
            for event in events
        ]

    @app.get("/briefing")
    async def get_briefing() -> list[BriefingItem]:
        """Phase 18 (docs/adr/0015): combines calendar/tasks/email/reminders/
        project events into one prioritized list. Like /calendar/reminders/due,
        this is a pure on-demand query, not a subscription — reachy-hub's
        POST /briefing/{user_id} calls it and does the greet + routing."""
        return await build_briefing(
            calendar_store=app.state.calendar_store,
            task_store=app.state.task_store,
            email_store=app.state.email_store,
            memory_store=app.state.memory_store,
            now=datetime.now(UTC),
        )

    @app.post("/memories")
    async def create_memory(request: CreateMemoryRequest) -> MemoryRecord:
        """Direct/API capture, alongside the conversational path in
        /conversation — e.g. to seed profile facts up front rather than
        waiting for them to come up naturally in conversation."""
        return await app.state.memory_store.add_memory(
            content=request.content,
            source="api",
            type=request.type,
            project_scope=request.project_scope,
            confidence=request.confidence,
            sensitivity=request.sensitivity or classify_privacy(request.content),
            expires_at=request.expires_at,
        )

    @app.get("/memories")
    async def list_memories(type: MemoryType | None = None) -> list[MemoryRecord]:
        return await app.state.memory_store.list_memories(type)

    @app.get("/memories/recall")
    async def recall_memories(q: str, type: MemoryType | None = None) -> list[MemoryRecord]:
        return await app.state.memory_store.recall(q, type=type)

    @app.post("/memories/{memory_id}/request-forget")
    async def request_forget_memory(memory_id: str) -> ConfirmationRequest:
        """docs/adr/0011: forgetting is destructive, so deleting a memory
        is now a two-step API too — this only *requests* a confirmation
        (SINGLE scope; request_confirmation refuses BULK unconditionally).
        Nothing is deleted until POST /memories/{id}/forget/confirm."""
        record = await app.state.memory_store.get(memory_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"no memory '{memory_id}'")
        return await request_confirmation(
            app.state.confirmation_store,
            action_type="memory.forget",
            target_id=record.id,
            description=record.content,
            scope=ActionScope.SINGLE,
        )

    @app.post("/memories/{memory_id}/forget/confirm")
    async def confirm_forget_memory(memory_id: str, request: ConfirmForgetRequest) -> MemoryRecord:
        # A direct API call is never voice — only /voice/turn's transcribed
        # conversational path can ever be — but confirm_action still runs
        # the same check, so this endpoint can't become a silent bypass of
        # the rule if that assumption ever stops holding.
        try:
            confirmed = await confirm_action(
                app.state.confirmation_store, request.confirmation_id, input_modality=InputModality.TEXT
            )
        except (ConfirmationNotFoundError, ConfirmationExpiredError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if confirmed.target_id != memory_id:
            raise HTTPException(status_code=400, detail="confirmation_id does not match this memory")
        record = await app.state.memory_store.forget(memory_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"no memory '{memory_id}'")
        return record

    @app.post("/memories/{memory_id}/restore")
    async def restore_memory(memory_id: str) -> MemoryRecord:
        """The undo — no confirmation needed, matches the conversational
        "restore X" path: undoing must never be harder than forgetting."""
        record = await app.state.memory_store.restore(memory_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"no forgotten memory '{memory_id}'")
        return record

    @app.post("/documents")
    async def ingest_document(request: CreateDocumentRequest) -> list[DocumentChunk]:
        """Operator/setup API, not an agent tool — nothing here crawls or
        pulls in documents on its own; this is how they get in at all."""
        return await app.state.rag_store.ingest_document(
            title=request.title, content=request.content, source=request.source
        )

    @app.get("/documents")
    async def list_documents() -> list[str]:
        return await app.state.rag_store.list_documents()

    @app.get("/documents/search")
    async def search_documents(q: str, top_k: int = 3) -> list[RetrievedChunk]:
        return await app.state.rag_store.search(q, top_k=top_k)

    @app.post("/emails/received")
    async def receive_email(request: ReceiveEmailRequest) -> EmailMessage:
        """Operator/setup API, not an agent tool — no external inbox sync
        exists, so this is how messages get into the store at all (same
        no-external-sync honesty as /calendar/events)."""
        return await app.state.email_store.add_received(
            sender=request.sender, subject=request.subject, body=request.body
        )

    @app.get("/emails/received")
    async def list_received_emails() -> list[EmailMessage]:
        return await app.state.email_store.list_received()

    @app.post("/emails/drafts")
    async def create_email_draft(request: CreateDraftRequest) -> EmailDraft:
        """Direct/API draft creation, alongside the conversational path —
        Prepare tier (docs/plan.md §9): generates a preview, no external
        change, no approval needed just to create it."""
        return await app.state.email_store.create_draft(
            to=request.to, subject=request.subject, body=request.body, in_reply_to=request.in_reply_to
        )

    @app.get("/emails/drafts")
    async def list_email_drafts(status: DraftStatus | None = None) -> list[EmailDraft]:
        return await app.state.email_store.list_drafts(status)

    @app.post("/emails/drafts/{draft_id}/approve")
    async def approve_email_draft(draft_id: str) -> EmailDraft:
        """Act-tier confirmation (docs/plan.md §9) — the only thing that
        moves a draft from DRAFT to APPROVED, which is what
        queue_draft_for_sending requires before it will queue anything. A
        direct API call is never voice (see forget/confirm's comment on
        the same point), so this always passes require_text — the check
        stays here anyway so it can't silently stop holding."""
        require_text(InputModality.TEXT)
        approved = await app.state.email_store.approve_draft(draft_id)
        if approved is None:
            raise HTTPException(status_code=404, detail=f"no pending draft '{draft_id}'")
        return approved

    @app.post("/emails/drafts/{draft_id}/send")
    async def send_email_draft(draft_id: str) -> EmailDraft:
        """docs/adr/0011: queues the send ~10 minutes out rather than
        dispatching immediately — the "changed your mind" window. See
        POST /emails/drafts/{id}/cancel-send for the undo, and
        run_dispatch_loop (started in lifespan) for what actually sends."""
        require_text(InputModality.TEXT)
        try:
            return await queue_draft_for_sending(app.state.email_store, draft_id, delay_seconds=email_send_delay_seconds)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DraftNotApprovedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/emails/drafts/{draft_id}/cancel-send")
    async def cancel_email_send(draft_id: str) -> EmailDraft:
        """The undo — no text-only gate, always allowed."""
        try:
            return await cancel_queued_draft(app.state.email_store, draft_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DraftNotQueuedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks")
    async def list_tasks(status: TaskStatus | None = None) -> list[Task]:
        return await app.state.task_store.list_tasks(status)

    @app.post("/tasks")
    async def create_task(request: CreateTaskRequest) -> Task:
        """Direct/API capture, alongside the conversational path in
        /conversation — e.g. for a future web UI that isn't going through a
        chat turn at all."""
        return await app.state.task_store.add_task(request.text)

    @app.post("/tasks/{task_id}/complete")
    async def complete_task_by_id(task_id: str) -> Task:
        task = await app.state.task_store.complete_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"no task '{task_id}'")
        return task

    @app.get("/tasks/search")
    async def search_tasks_endpoint(q: str) -> list[Task]:
        return await app.state.task_store.search_tasks(q)

    @app.get("/debug/robots/{robot_id}/state")
    async def debug_robot_state(robot_id: str) -> dict:
        try:
            return await app.state.hub_client.get_robot_state(robot_id)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"reachy-hub unreachable: {exc}") from exc

    @app.post("/debug/robots/{robot_id}/behaviour/{name}")
    async def debug_trigger_behaviour(robot_id: str, name: str) -> dict:
        try:
            return await app.state.hub_client.trigger_behaviour(robot_id, name)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"reachy-hub unreachable: {exc}") from exc

    return app
