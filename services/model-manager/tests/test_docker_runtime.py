"""The Docker side, with a fake command runner and a mock vLLM: command assembly and what 'ready' means."""

import httpx
import pytest
from model_manager.config import ManagerConfig, load_config
from model_manager.runtime import DockerRuntime, RuntimeFailure

from shared.models.model_manager import ModelTier

pytestmark = pytest.mark.anyio
T1, T2 = ModelTier.T1, ModelTier.T2


class Docker:
    """Records commands and answers `docker inspect` from a table of containers."""

    def __init__(self, containers: dict[str, bool] | None = None) -> None:
        self.containers = containers if containers is not None else {"reachy-homelab-vllm-1": True}
        self.commands: list[list[str]] = []
        self.logs = "CUDA out of memory"
        self.fail_on: set[str] = set()

    async def __call__(self, cmd: list[str]) -> tuple[int, str, str]:
        self.commands.append(cmd)
        if cmd[0] != "docker":
            return 0, "", ""
        verb = cmd[1]
        if verb in self.fail_on:
            return 1, "", f"{verb} exploded"
        if verb == "inspect":
            name = cmd[-1]
            if name not in self.containers:
                return 1, "", "No such object"
            return 0, "true\n" if self.containers[name] and "{{.State.Running}}" in cmd else f"/{name}\n", ""
        if verb == "logs":
            return 0, self.logs, ""
        if verb == "run":
            self.containers[cmd[cmd.index("--name") + 1]] = True
        if verb == "rm":
            self.containers.pop(cmd[-1], None)
        if verb == "stop":
            self.containers[cmd[-1]] = False
        if verb == "start":
            self.containers[cmd[-1]] = True
        return 0, "", ""


def vllm(health: int = 200, completion: int = 200, content: str = "ok") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(health)
        body = {"choices": [{"message": {"content": content}}]}
        return httpx.Response(completion, json=body)

    return httpx.MockTransport(handler)


def runtime(docker: Docker, transport=None, clock=None, sleep=None) -> DockerRuntime:
    async def no_sleep(_: float) -> None:
        return None

    return DockerRuntime(ManagerConfig(), runner=docker, transport=transport or vllm(), sleep=sleep or no_sleep,
                         **({"clock": clock} if clock else {}))


async def test_the_deep_container_is_launched_with_the_stable_name_a_no_restart_policy_and_the_thinking_switch() -> None:
    docker = Docker()
    await runtime(docker).start_tier(T2)
    run = next(c for c in docker.commands if c[:2] == ["docker", "run"])
    joined = " ".join(run)
    assert "--served-model-name reachy-local" in joined  # callers never see the underlying model id
    assert "--restart no" in joined  # a reboot must never bring the deep model back
    assert "--network-alias vllm" in joined and "127.0.0.1:8003:8000" in joined
    assert "Qwen/Qwen3-14B-AWQ" in run and '{"enable_thinking": false}' in run
    assert "--gpus" in run and "--ipc=host" in run


async def test_the_fast_tier_is_started_as_it_was_created_so_restoration_matches_the_original() -> None:
    docker = Docker({"reachy-homelab-vllm-1": False})
    await runtime(docker).start_tier(T1)
    assert ["docker", "start", "reachy-homelab-vllm-1"] in docker.commands
    assert not any(c[:2] == ["docker", "run"] for c in docker.commands)  # never re-created with different options


async def test_a_missing_fast_container_is_recreated_by_the_repo_script() -> None:
    docker = Docker({})
    await runtime(docker).start_tier(T1)
    assert ["scripts/start-vllm.sh"] in docker.commands


async def test_stopping_the_deep_tier_removes_it_and_tolerates_it_being_absent() -> None:
    docker = Docker({})
    await runtime(docker).stop_tier(T2)
    assert ["docker", "rm", "-f", "reachy-vllm-deep"] in docker.commands


async def test_stopping_the_fast_tier_stops_it_without_removing_it() -> None:
    docker = Docker()
    await runtime(docker).stop_tier(T1)
    assert any(c[:2] == ["docker", "stop"] for c in docker.commands)
    assert not any(c[:2] == ["docker", "rm"] for c in docker.commands)


async def test_a_docker_error_becomes_a_runtime_failure_with_the_message() -> None:
    docker = Docker()
    docker.fail_on = {"stop"}
    with pytest.raises(RuntimeFailure, match="stop exploded"):
        await runtime(docker).stop_tier(T1)


async def test_ready_needs_the_container_health_and_a_real_completion() -> None:
    docker = Docker()
    assert await runtime(docker, vllm()).is_ready(T1) is True
    assert await runtime(docker, vllm(health=503)).is_ready(T1) is False  # loaded but not healthy
    assert await runtime(docker, vllm(completion=500)).is_ready(T1) is False  # healthy but wedged
    assert await runtime(docker, vllm(content="")).is_ready(T1) is False  # answers with nothing
    assert await runtime(Docker({"reachy-homelab-vllm-1": False}), vllm()).is_ready(T1) is False  # not running


async def test_the_readiness_probe_uses_the_stable_model_name() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    await runtime(Docker(), httpx.MockTransport(handler)).is_ready(T1)
    import json

    assert json.loads(next(r for r in seen if r.url.path.endswith("completions")).content)["model"] == "reachy-local"


async def test_wait_ready_fails_fast_when_the_container_exits_and_shows_why() -> None:
    docker = Docker({"reachy-vllm-deep": False})
    with pytest.raises(RuntimeFailure, match="exited before it was ready: CUDA out of memory"):
        await runtime(docker).wait_ready(T2, 600)


async def test_wait_ready_times_out_when_the_model_never_answers() -> None:
    ticks = iter(range(0, 10_000, 100))
    docker = Docker({"reachy-vllm-deep": True})
    with pytest.raises(RuntimeFailure, match="not ready within 300 s"):
        await runtime(docker, vllm(health=503), clock=lambda: next(ticks)).wait_ready(T2, 300)


def test_config_file_overrides_selected_fields(tmp_path) -> None:
    path = tmp_path / "manager.json"
    path.write_text('{"t2": {"model": "google/gemma-4-12B-it-qat-w4a16-ct", "extra_args": []}, "host_port": 8010}')
    config = load_config(str(path))
    assert config.t2.model.startswith("google/gemma-4") and config.t2.extra_args == ()
    assert config.t2.container == "reachy-vllm-deep" and config.t1.model == "Qwen/Qwen2.5-7B-Instruct-AWQ"
    assert config.host_port == 8010 and config.served_model_name == "reachy-local"
