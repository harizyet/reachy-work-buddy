"""29.2: container runtime. This is the one place that actually shells out
to Docker — session/provider logic (service.py, providers.py) never does.
Security defaults (29.18) are baked into how a ContainerSpec is turned into
a `docker run` invocation, not left to each caller to remember: no
--privileged, no Docker socket mount, no host PID namespace, an explicit
--network, and explicit --cpus/--memory limits.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

# 29.27: labels every container this service starts, so a restarted
# supervisor can rediscover them with `docker ps --filter label=...`
# instead of trusting its own possibly-stale session store alone.
LABEL_PROJECT_ID = "reachy.project_id"
LABEL_SESSION_ID = "reachy.session_id"
LABEL_PROVIDER = "reachy.provider"


class ContainerStatus(StrEnum):
    RUNNING = "running"
    EXITED = "exited"
    MISSING = "missing"


class ContainerRuntimeError(Exception):
    pass


@dataclass
class ContainerSpec:
    """29.3/29.18: what a provider adapter asks the runtime to start. The
    adapter decides the image/command; this module decides how that
    becomes a sandboxed `docker run` — a provider can never smuggle in
    --privileged or a socket mount through this shape."""

    image: str
    project_id: str
    session_id: str
    provider: str
    host_mount_path: str
    container_mount_path: str = "/workspace"
    command: list[str] | None = None
    env: dict[str, str] = field(default_factory=dict)
    # 29.18: "offline" (no network), "restricted-network" (a named bridge
    # the deployment allowlists) or "development-network" (the default
    # Docker bridge) — never host networking.
    network_profile: str = "restricted-network"
    cpu_limit: str = "2"
    memory_limit: str = "2g"
    user: str = "1000:1000"
    # 29.3: a filesystem-enforced guardrail, independent of whatever the
    # process inside the container does or claims — set True and the mount
    # is `:ro`, so even a shell escape or a CLI policy bug cannot write to
    # the real project. See claude_provider.py's forced use of this for a
    # Claude Pro/Max subscription credential.
    read_only_mount: bool = False


class ContainerRuntime(Protocol):
    async def start(self, spec: ContainerSpec) -> str: ...
    async def stop(self, container_id: str, *, timeout: int = 10) -> None: ...
    async def status(self, container_id: str) -> ContainerStatus: ...
    async def logs(self, container_id: str) -> str:
        """29.3: a provider adapter's own way of reading what its CLI
        printed — never parsed by anything outside the provider, same
        boundary as the rest of this module keeping Docker specifics out
        of service.py/providers.py."""
        ...
    async def list_by_session(self, session_id: str) -> list[str]: ...
    async def list_labeled(self) -> dict[str, dict[str, str]]:
        """29.27 reconciliation: every container this runtime labeled,
        mapping container_id -> its reachy.* labels, regardless of which
        in-memory session object (if any) currently references it."""
        ...


class SimulatedContainerRuntime:
    """Default/test runtime — no real Docker involved. Mirrors the
    SimulatedProvider's role in providers.py: lets the rest of the service
    be exercised before a real container image exists."""

    def __init__(self) -> None:
        self._containers: dict[str, dict[str, str]] = {}
        self._status: dict[str, ContainerStatus] = {}
        self._logs: dict[str, str] = {}
        # Test-only introspection, same spirit as set_logs below — a
        # provider test can assert on exactly what spec (env, mounts,
        # network profile) its provider asked the runtime to start.
        self.specs: dict[str, ContainerSpec] = {}
        self._next_id = 0

    async def start(self, spec: ContainerSpec) -> str:
        self._next_id += 1
        container_id = f"sim-container-{self._next_id}"
        self._containers[container_id] = {
            LABEL_PROJECT_ID: spec.project_id,
            LABEL_SESSION_ID: spec.session_id,
            LABEL_PROVIDER: spec.provider,
        }
        self._status[container_id] = ContainerStatus.RUNNING
        self._logs[container_id] = ""
        self.specs[container_id] = spec
        return container_id

    async def stop(self, container_id: str, *, timeout: int = 10) -> None:
        if container_id in self._status:
            self._status[container_id] = ContainerStatus.EXITED

    async def status(self, container_id: str) -> ContainerStatus:
        return self._status.get(container_id, ContainerStatus.MISSING)

    async def logs(self, container_id: str) -> str:
        return self._logs.get(container_id, "")

    def set_logs(self, container_id: str, logs: str) -> None:
        """Test-only hook: seed a container's stdout so a provider's
        log-parsing logic can be exercised without a real `claude` process."""
        self._logs[container_id] = logs

    async def list_by_session(self, session_id: str) -> list[str]:
        return [cid for cid, labels in self._containers.items() if labels[LABEL_SESSION_ID] == session_id]

    async def list_labeled(self) -> dict[str, dict[str, str]]:
        return dict(self._containers)


class DockerCLIContainerRuntime:
    """Real runtime, shelling out to the `docker` CLI (no extra Python
    Docker-SDK dependency — every other service in this repo already talks
    to peer services over HTTP, not a client library, and the CLI is what
    the host actually has installed). `label_prefix` scopes
    `list_labeled`'s discovery query so it only ever sees containers this
    service itself started, never unrelated homelab containers that happen
    to run on the same host."""

    def __init__(self, *, label_prefix: str = "reachy") -> None:
        self._label_prefix = label_prefix

    async def _run(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise ContainerRuntimeError(stderr.decode(errors="replace").strip() or f"docker {args[0]} failed")
        return stdout.decode()

    async def start(self, spec: ContainerSpec) -> str:
        network_args = ["--network", "none"] if spec.network_profile == "offline" else ["--network", spec.network_profile]
        args = [
            "run",
            "--detach",
            "--user",
            spec.user,
            "--cpus",
            spec.cpu_limit,
            "--memory",
            spec.memory_limit,
            # 29.18: no --privileged, no --pid=host, no device passthrough,
            # no Docker socket mount — none of those flags exist here, by
            # construction, not by caller discipline.
            "--security-opt",
            "no-new-privileges",
            "--volume",
            f"{spec.host_mount_path}:{spec.container_mount_path}:{'ro' if spec.read_only_mount else 'rw'}",
            *network_args,
            "--label",
            f"{LABEL_PROJECT_ID}={spec.project_id}",
            "--label",
            f"{LABEL_SESSION_ID}={spec.session_id}",
            "--label",
            f"{LABEL_PROVIDER}={spec.provider}",
        ]
        for key, value in spec.env.items():
            args += ["--env", f"{key}={value}"]
        args.append(spec.image)
        if spec.command:
            args += spec.command
        output = await self._run(*args)
        return output.strip()

    async def stop(self, container_id: str, *, timeout: int = 10) -> None:
        await self._run("stop", "--time", str(timeout), container_id)

    async def status(self, container_id: str) -> ContainerStatus:
        try:
            output = await self._run("inspect", "--format", "{{.State.Status}}", container_id)
        except ContainerRuntimeError:
            return ContainerStatus.MISSING
        state = output.strip()
        return ContainerStatus.RUNNING if state == "running" else ContainerStatus.EXITED

    async def logs(self, container_id: str) -> str:
        try:
            return await self._run("logs", container_id)
        except ContainerRuntimeError:
            return ""

    async def list_by_session(self, session_id: str) -> list[str]:
        # --no-trunc: `docker run`'s own stdout (used as the id returned
        # from start()) is always the full 64-char id, but `docker ps`
        # truncates to 12 by default — without this flag, callers that
        # compare against start()'s return value would never find a match.
        output = await self._run(
            "ps", "--all", "--no-trunc", "--filter", f"label={LABEL_SESSION_ID}={session_id}", "--format", "{{.ID}}"
        )
        return [line for line in output.splitlines() if line]

    async def list_labeled(self) -> dict[str, dict[str, str]]:
        output = await self._run(
            "ps",
            "--all",
            "--no-trunc",
            "--filter",
            f"label={self._label_prefix}.session_id",
            "--format",
            "{{.ID}}\t{{.Labels}}",
        )
        result: dict[str, dict[str, str]] = {}
        for line in output.splitlines():
            if not line.strip():
                continue
            container_id, _, raw_labels = line.partition("\t")
            labels = {}
            for pair in raw_labels.split(","):
                key, _, value = pair.partition("=")
                if key.startswith(f"{self._label_prefix}."):
                    labels[key] = value
            result[container_id] = labels
        return result
