from reachy_hub.response_policy import apply_privacy_override, resolve_delivery_channel

from shared.models.response import Privacy
from shared.models.session import Channel, InteractionMode


def test_desk_mode_always_routes_to_reachy() -> None:
    assert resolve_delivery_channel(InteractionMode.DESK, Channel.TELEGRAM) == Channel.REACHY


def test_office_mode_prefers_phone() -> None:
    assert resolve_delivery_channel(InteractionMode.OFFICE, Channel.REACHY) == Channel.PHONE


def test_remote_mode_prefers_phone() -> None:
    assert resolve_delivery_channel(InteractionMode.REMOTE, Channel.WEB) == Channel.PHONE


def test_silent_mode_stays_on_current_text_channel() -> None:
    assert resolve_delivery_channel(InteractionMode.SILENT, Channel.TELEGRAM) == Channel.TELEGRAM
    assert resolve_delivery_channel(InteractionMode.SILENT, Channel.WEB) == Channel.WEB


def test_silent_mode_falls_back_to_web_if_active_channel_is_reachy() -> None:
    # Reachy has no silent/text-only output path.
    assert resolve_delivery_channel(InteractionMode.SILENT, Channel.REACHY) == Channel.WEB


def test_policy_is_pure_and_ignores_anything_but_mode_and_channel() -> None:
    """The exit criterion, structurally: the function has no parameter for
    response content, so it cannot possibly route based on what was said."""
    import inspect

    params = list(inspect.signature(resolve_delivery_channel).parameters)
    assert params == ["mode", "active_channel"]


# --- Phase 9: apply_privacy_override ---


def test_sensitive_content_is_never_routed_to_reachy() -> None:
    assert apply_privacy_override(Channel.REACHY, Privacy.SENSITIVE, Channel.TELEGRAM) == Channel.TELEGRAM


def test_work_private_content_is_never_routed_to_reachy() -> None:
    assert apply_privacy_override(Channel.REACHY, Privacy.WORK_PRIVATE, Channel.WEB) == Channel.WEB


def test_public_content_is_unaffected() -> None:
    assert apply_privacy_override(Channel.REACHY, Privacy.PUBLIC, Channel.TELEGRAM) == Channel.REACHY


def test_override_falls_back_to_web_when_active_channel_is_also_reachy() -> None:
    assert apply_privacy_override(Channel.REACHY, Privacy.SENSITIVE, Channel.REACHY) == Channel.WEB


def test_override_never_fires_when_base_channel_is_not_reachy() -> None:
    """apply_privacy_override can only ever veto a Reachy delivery that
    resolve_delivery_channel already chose — it never introduces routing to
    a *different* non-Reachy channel than the mode policy picked."""
    assert apply_privacy_override(Channel.PHONE, Privacy.SENSITIVE, Channel.TELEGRAM) == Channel.PHONE
