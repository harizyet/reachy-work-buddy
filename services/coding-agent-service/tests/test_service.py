"""29.1 exit criterion: "A simulated provider can create and transition a
durable coding session." Exercises CodingAgentSupervisor directly against
SimulatedProvider + InMemoryCodingAgentStore — no HTTP layer needed to prove
the state machine itself.
"""

import asyncio

import pytest
from coding_agent_service.providers import ProviderError, SimulatedProvider
from coding_agent_service.service import (
    CodingAgentSupervisor,
    SessionNotResumableError,
    UnknownProjectError,
    UnknownProviderError,
)
from coding_agent_service.store import InMemoryCodingAgentStore

from shared.models.coding_agent import (
    CodingAgentEventType,
    CodingAgentStatus,
    CodingProject,
)


def _supervisor() -> CodingAgentSupervisor:
    return CodingAgentSupervisor(InMemoryCodingAgentStore(), {"simulated": SimulatedProvider()})


def test_simulated_provider_creates_and_completes_a_session() -> None:
    async def run() -> None:
        supervisor = _supervisor()
        project = await supervisor.add_project(
            CodingProject(name="Reachy Work Buddy", repository_path="/projects/reachy-work-buddy", provider="simulated")
        )

        session = await supervisor.start_session(
            project_id=project.id, task_summary="Refactor module X", owner_user_id="owner-1"
        )

        assert session.status == CodingAgentStatus.COMPLETED
        assert session.provider_session_id is not None
        assert session.completed_at is not None

        stored = await supervisor.get_session(session.id)
        assert stored.status == CodingAgentStatus.COMPLETED

        events = await supervisor.list_events(session.id)
        event_types = [e.type for e in events]
        assert CodingAgentEventType.AGENT_STARTED in event_types
        assert CodingAgentEventType.AGENT_COMPLETED in event_types

    asyncio.run(run())


def test_session_waiting_for_input_resumes_with_owner_instruction() -> None:
    async def run() -> None:
        supervisor = _supervisor()
        project = await supervisor.add_project(
            CodingProject(name="Reachy Work Buddy", repository_path="/projects/reachy-work-buddy", provider="simulated")
        )

        session = await supervisor.start_session(
            project_id=project.id,
            task_summary="ask: which migration strategy should I use?",
            owner_user_id="owner-1",
        )
        assert session.status == CodingAgentStatus.WAITING_FOR_INPUT

        resumed = await supervisor.resume_session(session.id, "Use a new migration.")
        assert resumed.status == CodingAgentStatus.COMPLETED
        assert "Use a new migration." in resumed.last_event

    asyncio.run(run())


def test_permission_request_is_not_auto_approved() -> None:
    async def run() -> None:
        supervisor = _supervisor()
        project = await supervisor.add_project(
            CodingProject(name="Reachy Work Buddy", repository_path="/projects/reachy-work-buddy", provider="simulated")
        )

        session = await supervisor.start_session(
            project_id=project.id,
            task_summary="permission: run sudo apt-get install",
            owner_user_id="owner-1",
        )
        assert session.status == CodingAgentStatus.WAITING_FOR_PERMISSION

        # Nothing in the supervisor moves a waiting-for-permission session
        # forward except an explicit owner decision relayed through resume.
        still_waiting = await supervisor.get_session(session.id)
        assert still_waiting.status == CodingAgentStatus.WAITING_FOR_PERMISSION

    asyncio.run(run())


def test_cannot_resume_a_running_or_terminal_session() -> None:
    async def run() -> None:
        supervisor = _supervisor()
        project = await supervisor.add_project(
            CodingProject(name="Reachy Work Buddy", repository_path="/projects/reachy-work-buddy", provider="simulated")
        )
        session = await supervisor.start_session(
            project_id=project.id, task_summary="Run tests", owner_user_id="owner-1"
        )
        assert session.status == CodingAgentStatus.COMPLETED

        with pytest.raises(SessionNotResumableError):
            await supervisor.resume_session(session.id, "keep going")

    asyncio.run(run())


def test_unknown_project_and_provider_are_rejected() -> None:
    async def run() -> None:
        supervisor = _supervisor()

        with pytest.raises(UnknownProjectError):
            await supervisor.start_session(project_id="missing", task_summary="x", owner_user_id="owner-1")

        project = await supervisor.add_project(
            CodingProject(name="X", repository_path="/x", provider="codex")
        )
        with pytest.raises(UnknownProviderError):
            await supervisor.start_session(project_id=project.id, task_summary="x", owner_user_id="owner-1")

    asyncio.run(run())


def test_stop_session_is_terminal_and_idempotent() -> None:
    async def run() -> None:
        supervisor = _supervisor()
        project = await supervisor.add_project(
            CodingProject(name="X", repository_path="/x", provider="simulated")
        )
        session = await supervisor.start_session(
            project_id=project.id,
            task_summary="ask: which approach?",
            owner_user_id="owner-1",
        )
        stopped = await supervisor.stop_session(session.id)
        assert stopped.status == CodingAgentStatus.STOPPED

        stopped_again = await supervisor.stop_session(session.id)
        assert stopped_again.status == CodingAgentStatus.STOPPED

    asyncio.run(run())


def test_resume_session_rejects_wrong_status_in_provider() -> None:
    async def run() -> None:
        provider = SimulatedProvider()
        supervisor = CodingAgentSupervisor(InMemoryCodingAgentStore(), {"simulated": provider})
        project = await supervisor.add_project(
            CodingProject(name="X", repository_path="/x", provider="simulated")
        )
        session = await supervisor.start_session(project_id=project.id, task_summary="done fast", owner_user_id="o")
        with pytest.raises(ProviderError):
            await provider.resume_session(session, "too late")

    asyncio.run(run())


def test_resume_increments_turn_and_a_suspected_completion_is_resumable() -> None:
    from coding_agent_service.providers import ProviderEvent

    from shared.models.coding_agent import InterventionState

    async def run() -> None:
        supervisor = _supervisor()
        project = await supervisor.add_project(
            CodingProject(name="P", repository_path="/p", provider="simulated")
        )
        session = await supervisor.start_session(
            project_id=project.id, task_summary="plain", owner_user_id="owner-1"
        )
        assert session.turn == 1
        with pytest.raises(SessionNotResumableError):
            await supervisor.resume_session(session.id, "more")

        await supervisor.apply_provider_event(
            session,
            ProviderEvent(
                status=CodingAgentStatus.COMPLETED,
                summary="Shall I proceed?",
                intervention_state=InterventionState.SUSPECTED,
                intervention_source="final_message_question",
            ),
        )
        resumed = await supervisor.resume_session(session.id, "yes")
        assert resumed.turn == 2
        assert resumed.intervention_state == InterventionState.NONE

    asyncio.run(run())
