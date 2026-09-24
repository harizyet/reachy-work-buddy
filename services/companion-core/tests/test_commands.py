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
