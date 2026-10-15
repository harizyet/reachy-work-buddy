"""Hub route constants for shared voice identity (Phase 32A, ADR 0041). Owner cookie
session only, no REMOTE_UI_TOKEN bearer; mutating routes also need CSRF and a fresh
re-authentication (OWNER_RECOGNITION_REAUTH)."""

VOICE_IDENTITY_STATUS = "/voice-identity/status"
VOICE_IDENTITY_ENROLL_SAMPLES = "/voice-identity/enrollment/samples"
VOICE_IDENTITY_ENROLL_SAMPLE = "/voice-identity/enrollment/samples/{sample_id}"
VOICE_IDENTITY_ENROLL_COMMIT = "/voice-identity/enrollment/commit"
VOICE_IDENTITY_ENROLL_DRAFT = "/voice-identity/enrollment"
VOICE_IDENTITY_PROFILE = "/voice-identity/profile"
VOICE_IDENTITY_VERIFY = "/voice-identity/verify"
VOICE_IDENTITY_TURN = "/voice-identity/turn"

# Request headers: provenance asserted by the client, plus the utterance it is about.
CLIENT_KIND_HEADER = "X-Reachy-Client-Kind"
CLIENT_ID_HEADER = "X-Reachy-Client-Id"
DEVICE_ID_HEADER = "X-Reachy-Device-Id"
UTTERANCE_ID_HEADER = "X-Reachy-Utterance-Id"
