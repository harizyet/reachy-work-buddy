from companion_core.commands.parser import Command, parse


def test_namespaced_form_parses_to_a_structured_command():
    assert parse("/reachy standby") == Command(namespace="reachy", action="standby")
    assert parse("/reachy wake") == Command(namespace="reachy", action="wake")
    assert parse("/reachy status") == Command(namespace="reachy", action="status")


def test_telegram_flat_aliases_parse_to_the_identical_command():
    assert parse("/standby") == Command(namespace="reachy", action="standby")
    assert parse("/wake") == Command(namespace="reachy", action="wake")
    assert parse("/reachy_status") == Command(namespace="reachy", action="status")


def test_unknown_action_and_unknown_alias_do_not_parse():
    assert parse("/reachy dance") is None
    assert parse("/reachy gesture greeting") is None
    assert parse("/nonsense") is None


def test_plain_text_never_parses_even_when_it_mentions_a_command_word():
    assert parse("please turn off reachy") is None
    assert parse("standby reachy") is None
    assert parse("") is None
    assert parse("   ") is None


def test_leading_whitespace_is_tolerated():
    assert parse("  /reachy standby  ") == Command(namespace="reachy", action="standby")


def test_all_menu_commands_parse_and_query_arguments_are_validated():
    from companion_core.commands.parser import query_usage_error

    from shared.protocols.commands import COMMANDS, QUERY_COMMANDS

    for alias, action, _, argument in COMMANDS:
        suffix = " My Topic" if argument else ""
        expected = Command("reachy", action, "My Topic" if argument else None)
        assert parse(f"/{alias}{suffix}") == expected
        assert parse(f"/{alias}@reachy_bot{suffix}") == expected
        assert parse(f"/reachy {action}{suffix}") == expected
    for alias, action, _, argument in QUERY_COMMANDS:
        valid = parse(f"/{alias}" + (" topic" if argument else ""))
        assert query_usage_error(valid) is None
        invalid = parse(f"/{alias}" + ("" if argument else " unexpected"))
        assert query_usage_error(invalid).startswith("Usage:")
