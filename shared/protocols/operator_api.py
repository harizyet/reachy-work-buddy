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

# Phase 25a.2/25b.3 (docs/phase-25.md "Enrollment portal"): raw
# voice/face sample capture only, no biometric template/model yet.
OWNER_RECOGNITION_STATUS = "/owner-recognition/status"
OWNER_RECOGNITION_REAUTH = "/owner-recognition/reauth"
OWNER_RECOGNITION_VOICE_SAMPLES = "/owner-recognition/voice/samples"
OWNER_RECOGNITION_VOICE_SAMPLE = "/owner-recognition/voice/samples/{sample_id}"
OWNER_RECOGNITION_FACE_SAMPLES = "/owner-recognition/face/samples"
OWNER_RECOGNITION_FACE_SAMPLE = "/owner-recognition/face/samples/{sample_id}"
