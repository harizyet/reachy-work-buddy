"""The Docker side of the manager. Everything that touches the host is behind `Runtime` so the state machine is
tested with injected failures and this class with a fake command runner."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx

from model_manager.config import ManagerConfig, TierConfig
from shared.models.model_manager import ModelTier


class RuntimeFailure(Exception):
    """A tier could not be started, stopped or made ready. The message is safe to show the owner."""


class ReadyTimeout(RuntimeFailure):
    """The tier started but never became ready in time. Not retried: a model that is merely slow will be slow again."""


class Runtime(Protocol):
    async def stop_tier(self, tier: ModelTier) -> None: ...
    async def start_tier(self, tier: ModelTier) -> None: ...
    async def wait_ready(self, tier: ModelTier, timeout_s: float) -> None: ...
    async def is_running(self, tier: ModelTier) -> bool: ...
    async def is_ready(self, tier: ModelTier) -> bool: ...


CommandRunner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]


async def run_command(cmd: list[str]) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await process.communicate()
    return process.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


class DockerRuntime:
    """Fast tier: the compose-created container, stopped and started as it is so restoration is bit-for-bit the
    original configuration. Deep tier: a separate container with `--restart no`, so a host reboot can never leave
    the deep model as the one that comes back."""

    def __init__(
        self, config: ManagerConfig, *, runner: CommandRunner = run_command,
        transport: httpx.AsyncBaseTransport | None = None, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config, self._run, self._transport, self._sleep, self._clock = config, runner, transport, sleep, clock

    async def _docker(self, *args: str, check: bool = True) -> str:
        code, out, err = await self._run(["docker", *args])
        if check and code != 0:
            raise RuntimeFailure(f"docker {args[0]} failed: {(err or out).strip()[-300:]}")
        return out

    async def is_running(self, tier: ModelTier) -> bool:
        code, out, _ = await self._run(["docker", "inspect", "-f", "{{.State.Running}}", self.config.tier(tier).container])
        return code == 0 and out.strip() == "true"

    async def _exists(self, name: str) -> bool:
        code, _, _ = await self._run(["docker", "inspect", "-f", "{{.Name}}", name])
        return code == 0

    async def stop_tier(self, tier: ModelTier) -> None:
        cfg = self.config.tier(tier)
        if tier == ModelTier.T2:
            await self._docker("rm", "-f", cfg.container, check=False)  # absent is fine
            return
        if await self.is_running(tier):
            await self._docker("stop", "-t", str(int(self.config.stop_timeout_s)), cfg.container)

    async def start_tier(self, tier: ModelTier) -> None:
        cfg = self.config.tier(tier)
        if tier == ModelTier.T1:
            if await self._exists(cfg.container):
                await self._docker("start", cfg.container)
                return
            code, out, err = await self._run(list(self.config.t1_create_command))
            if code != 0:
                raise RuntimeFailure(f"creating the fast tier failed: {(err or out).strip()[-300:]}")
            return
        await self._docker("rm", "-f", cfg.container, check=False)
        await self._docker(*self.t2_run_args(cfg))

    def t2_run_args(self, cfg: TierConfig) -> list[str]:
        c = self.config
        return [
            "run", "-d", "--name", cfg.container, "--restart", "no", "--gpus", "all", "--ipc=host",
            "--network", c.network, "--network-alias", c.network_alias,
            "-e", "HF_HUB_DISABLE_XET=1",
            "-v", f"{c.cache_dir}/huggingface:/root/.cache/huggingface", "-v", f"{c.cache_dir}/vllm:/root/.cache/vllm",
            "-p", f"127.0.0.1:{c.host_port}:8000", c.image, cfg.model,
            "--served-model-name", c.served_model_name,
            "--max-model-len", str(cfg.max_model_len), "--gpu-memory-utilization", str(cfg.gpu_memory_utilization),
            *cfg.extra_args,
        ]

    async def is_ready(self, tier: ModelTier) -> bool:
        """Ready means the container runs, /health answers AND a one-token completion works: a loaded but wedged
        server must not count as ready."""
        if not await self.is_running(tier):
            return False
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=30.0) as client:
                if (await client.get(self.config.endpoint + "/health")).status_code != 200:
                    return False
                reply = await client.post(
                    self.config.endpoint + "/v1/chat/completions",
                    json={"model": self.config.served_model_name, "max_tokens": 4, "temperature": 0,
                          "messages": [{"role": "user", "content": "Reply with: ok"}]},
                )
                return reply.status_code == 200 and bool(reply.json()["choices"][0]["message"].get("content"))
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            return False

    async def wait_ready(self, tier: ModelTier, timeout_s: float) -> None:
        cfg = self.config.tier(tier)
        deadline = self._clock() + timeout_s
        while self._clock() < deadline:
            if not await self.is_running(tier):
                logs = (await self._docker("logs", "--tail", "5", cfg.container, check=False)).strip()[-300:]
                raise RuntimeFailure(f"{tier.value} container exited before it was ready: {logs}")
            if await self.is_ready(tier):
                return
            await self._sleep(5.0)
        raise ReadyTimeout(f"{tier.value} was not ready within {int(timeout_s)} s")
