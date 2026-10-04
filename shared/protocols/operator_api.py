"""Operator routes shared by the hub proxy and core service."""

LLM_SETTINGS = "/settings/llm"
LLM_USAGE = "/llm/usage"
PERSONA_SETTINGS = "/settings/persona"
WEBSEARCH_SETTINGS = "/settings/websearch"
# Phase 24a follow-up: in-memory owner debug view of recent searches.
WEBSEARCH_LOG = "/websearch/log"
STATUS = "/status"
AUTH_LOGIN = "/auth/login"
AUTH_LOGOUT = "/auth/logout"
AUTH_ME = "/auth/me"
ROBOTS = "/robots"
ROBOTS_STANDBY = "/robots/standby"
ROBOTS_RESUME = "/robots/resume"
# Phase 24c (ADR 0023): owner controls for robot microphone conversation.
ROBOT_VOICE = "/robot-voice"
ROBOT_VOICE_START = "/robot-voice/start"
ROBOT_VOICE_RENEW = "/robot-voice/renew"
ROBOT_VOICE_STOP = "/robot-voice/stop"
# Phase 24g: owner arms or disarms spoken wake monitoring for one robot.
ROBOT_VOICE_WAKE = "/robot-voice/wake"

ROBOT_MOTION_SETTINGS = "/robots/{robot_id}/settings/motion"

# Phase 25a.2/25b.3 (docs/phase-25.md "Enrollment portal"), Phase 26d
# (docs/phase-26.md's benchmark-vs-operational data policy): raw
# voice/face sample capture, explicitly namespaced under "benchmark" —
# no biometric template/model, no operational enrollment, yet. A future
# operational store would live under a separate "/owner-recognition/
# enrollment/..." namespace, never this one.
OWNER_RECOGNITION_STATUS = "/owner-recognition/status"
OWNER_RECOGNITION_REAUTH = "/owner-recognition/reauth"
OWNER_RECOGNITION_BENCHMARK_ENABLED = "/owner-recognition/benchmark/enabled"
OWNER_RECOGNITION_BENCHMARK_VOICE_SAMPLES = "/owner-recognition/benchmark/voice/samples"
OWNER_RECOGNITION_BENCHMARK_VOICE_SAMPLE = "/owner-recognition/benchmark/voice/samples/{sample_id}"
OWNER_RECOGNITION_BENCHMARK_FACE_SAMPLES = "/owner-recognition/benchmark/face/samples"
OWNER_RECOGNITION_BENCHMARK_FACE_SAMPLE = "/owner-recognition/benchmark/face/samples/{sample_id}"
OWNER_RECOGNITION_BENCHMARK_VOICE_EXPORT = "/owner-recognition/benchmark/voice/export"
OWNER_RECOGNITION_BENCHMARK_FACE_EXPORT = "/owner-recognition/benchmark/face/export"

# Phase 27.1 (docs/phase-27.md): meeting intelligence foundation. Owner-only
# proxies to companion-core's /meetings — core itself is closed to the
# browser (only /core/health is exposed through Caddy).
MEETINGS = "/meetings"
MEETING = "/meetings/{meeting_id}"
MEETING_CANCEL = "/meetings/{meeting_id}/cancel"

# Hub-owned web transcript records.
CHATS = "/chats"
CHAT = "/chats/{chat_id}"

# Owner to-do / reminders / notes. Hub proxies to companion-core's /tasks,
# /reminders and /notes under this prefix.
PLANNER_PREFIX = "/planner"
PLANNER_TASKS = "/planner/tasks"
PLANNER_TASK = "/planner/tasks/{item_id}"
PLANNER_TASK_COMPLETE = "/planner/tasks/{item_id}/complete"
PLANNER_TASK_REOPEN = "/planner/tasks/{item_id}/reopen"
PLANNER_NOTES = "/planner/notes"
PLANNER_NOTE = "/planner/notes/{item_id}"
PLANNER_REMINDERS = "/planner/reminders"
PLANNER_REMINDER = "/planner/reminders/{item_id}"
PLANNER_REMINDER_COMPLETE = "/planner/reminders/{item_id}/complete"
