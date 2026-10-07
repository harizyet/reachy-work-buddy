"""Manager configuration. Defaults mirror deploy/homelab/docker-compose.yml's vllm service and the benchmarked Qwen3-14B launch."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from shared.models.model_manager import ModelTier
from shared.protocols.model_manager_api import LOCAL_MODEL_NAME


@dataclass(frozen=True)
class TierConfig:
    tier: ModelTier
    model: str  # the Hugging Face id: only the manager ever knows this
    container: str
    max_model_len: int = 8192
    gpu_memory_utilization: float = 0.85
    # Per-model launch arguments (for example Qwen3's thinking switch) belong to the model, not to its callers.
    extra_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManagerConfig:
    t1: TierConfig = field(
        default_factory=lambda: TierConfig(
            ModelTier.T1, "Qwen/Qwen2.5-7B-Instruct-AWQ", "reachy-homelab-vllm-1"
        )
    )
    t2: TierConfig = field(
        default_factory=lambda: TierConfig(
            ModelTier.T2, "Qwen/Qwen3-14B-AWQ", "reachy-vllm-deep",
            extra_args=("--default-chat-template-kwargs", '{"enable_thinking": false}'),
        )
    )
    served_model_name: str = LOCAL_MODEL_NAME
    # Both tiers are reachable here: the compose vllm service and the deep container publish the same host port.
    endpoint: str = "http://127.0.0.1:8003"
    image: str = "vllm/vllm-openai:latest"
    network: str = "reachy-homelab_default"
    network_alias: str = "vllm"  # what companion-core resolves, whichever tier is running
    host_port: int = 8003
    cache_dir: str = str(Path.home() / "vllm" / "cache")
    # Creates the fast tier's container if it does not exist (normally compose created it and `docker start` suffices).
    t1_create_command: tuple[str, ...] = ("scripts/start-vllm.sh",)
    t2_ready_timeout_s: float = 600.0
    t1_ready_timeout_s: float = 900.0
    stop_timeout_s: float = 60.0
    restore_retries: int = 1  # one retry after a failed restore, then FAILED: never an unbounded loop
    t2_start_retries: int = 1  # a crashed or failed deep start is retried once, then the fast tier is loaded
    t2_retry_delay_s: float = 5.0
    watch_interval_s: float = 15.0  # how often a loaded deep tier is checked for a crash or hang
    watch_unhealthy_checks: int = 3  # consecutive failed health checks (a crash is acted on at once)
    default_lease_s: float = 1800.0
    max_lease_s: float = 6 * 3600.0
    transitions_log: str | None = None  # JSONL history; never read back as state

    def tier(self, tier: ModelTier) -> TierConfig:
        return self.t1 if tier == ModelTier.T1 else self.t2


def load_config(path: str | None = None) -> ManagerConfig:
    """Defaults, overridden by a JSON file (MODEL_MANAGER_CONFIG) when given."""
    path = path or os.environ.get("MODEL_MANAGER_CONFIG")
    if not path:
        return ManagerConfig()
    raw = json.loads(Path(path).read_text())
    base = ManagerConfig()
    for name in ("t1", "t2"):
        if name in raw:
            current = getattr(base, name)
            raw[name] = TierConfig(**{**current.__dict__, **raw[name], "tier": current.tier,
                                      "extra_args": tuple(raw[name].get("extra_args", current.extra_args))})
    if "t1_create_command" in raw:
        raw["t1_create_command"] = tuple(raw["t1_create_command"])
    return ManagerConfig(**{**base.__dict__, **raw})
