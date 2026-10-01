"""Command metadata shared by core's parser and hub's Telegram menu."""

# alias, canonical /reachy action, description, required argument label
QUERY_COMMANDS = (
    ("help", "help", "Show available commands", None),
    ("coding_sessions", "coding_sessions", "Show recorded coding-agent session status", None),
    ("coding_usage", "coding_usage", "Show recorded coding-agent usage", None),
    ("today", "today", "Show today's calendar", None),
    ("next_event", "next_event", "Show your next calendar event", None),
    ("tasks", "tasks", "List open tasks", None),
    ("find_tasks", "find_tasks", "Search tasks: /find_tasks words", "words"),
    ("inbox", "inbox", "List received emails", None),
    ("recall", "recall", "Recall saved memories: /recall topic", "topic"),
    ("docs", "docs", "Search stored documents: /docs topic", "topic"),
    ("time", "time", "Show the time in your configured timezone", None),
    ("date", "date", "Show the date in your configured timezone", None),
)
ROBOT_COMMANDS = (
    ("standby", "standby", "Put Reachy into standby", None),
    ("wake", "wake", "Wake Reachy up", None),
    ("reachy_status", "status", "Check Reachy's status", None),
)
COMMANDS = QUERY_COMMANDS + ROBOT_COMMANDS
TELEGRAM_COMMANDS = [{"command": alias, "description": description} for alias, _, description, _ in COMMANDS]
