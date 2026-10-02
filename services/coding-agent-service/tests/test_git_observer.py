import asyncio

from coding_agent_service.git_observer import GitObserver
from coding_agent_service.runtime import SimulatedContainerRuntime

_SAFE = ["-c", "safe.directory=/workspace"]


def test_observation_reports_head_branch_and_changed_files() -> None:
    runtime = SimulatedContainerRuntime()
    runtime.run_once_outputs = {
        (*_SAFE, "rev-parse", "HEAD"): "abc123\n",
        (*_SAFE, "rev-parse", "--abbrev-ref", "HEAD"): "main\n",
        (*_SAFE, "status", "--porcelain"): " M a.py\n?? b.py\n",
    }
    state = asyncio.run(GitObserver(runtime, "img").observe("/repo"))
    assert state.head == "abc123"
    assert state.branch == "main"
    assert state.dirty is True
    assert state.changed_files == ["a.py", "b.py"]
    assert runtime.run_once_calls[0][0] == "/repo"


def test_unreadable_repository_yields_no_state() -> None:
    class Broken(SimulatedContainerRuntime):
        async def run_once(self, **_kw) -> str:
            raise RuntimeError("not a git repository")

    assert asyncio.run(GitObserver(Broken(), "img").observe("/x")) is None
