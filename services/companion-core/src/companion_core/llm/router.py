"""Role policy: only actual provider failure or explicit user choice escalates."""

from companion_core.llm.client import OpenAICompatibleChatProvider, ProviderUnavailable
from companion_core.llm.store import LLMUsageStore
from shared.models.llm import LLMConfig, LLMRole, LLMRoutingMode


def role_order(
    config: LLMConfig, *, force_frontier: bool = False
) -> tuple[LLMRole, ...]:
    if force_frontier or config.routing.mode == LLMRoutingMode.CLOUD_ONLY:
        return (LLMRole.CLOUD,)
    if config.routing.mode == LLMRoutingMode.LOCAL_WITH_CLOUD_FALLBACK:
        return (LLMRole.LOCAL, LLMRole.CLOUD)
    return (LLMRole.LOCAL,)


async def route_completion(
    config: LLMConfig,
    history: list[dict[str, str]],
    usage: LLMUsageStore,
    *,
    force_frontier: bool = False,
    transport=None,
    local_max_tokens: int | None = None,
) -> str:
    """`local_max_tokens` caps only the local model: a reasoning cloud model
    (GLM-5.3) spends its completion budget on reasoning and returns empty
    content under a small cap, which would turn a fallback into a failure."""
    providers = {LLMRole.LOCAL: config.local, LLMRole.CLOUD: config.cloud}
    for index, role in enumerate(role_order(config, force_frontier=force_frontier)):
        provider_config = providers[role]
        if provider_config is None:
            raise ProviderUnavailable("Requested provider is not configured")
        reason = "manual" if force_frontier else "error" if index else None
        provider = OpenAICompatibleChatProvider(
            provider_config,
            usage,
            role=role,
            escalation_reason=reason,
            transport=transport,
        )
        try:
            return await provider.complete(
                history, max_tokens=local_max_tokens if role == LLMRole.LOCAL else None
            )
        except ProviderUnavailable:
            # Cancellation and persistence errors must not dispatch another call.
            continue
    raise ProviderUnavailable("Configured providers are unavailable")
