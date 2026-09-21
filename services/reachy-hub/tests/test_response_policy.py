from reachy_hub.response_policy import resolve_delivery_channel

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
