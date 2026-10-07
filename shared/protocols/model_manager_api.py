"""Model manager routes and the stable local model identity (ADR 0031)."""

# Every tier is served under this one API-visible name (vLLM --served-model-name), so callers never learn which
# underlying model is loaded and a tier swap cannot break a client's configured model.
LOCAL_MODEL_NAME = "reachy-local"

MANAGER_HEALTH = "/health"
MANAGER_STATE = "/state"
MANAGER_ACTIVATE = "/tier/activate"
MANAGER_RESTORE = "/tier/restore"
MANAGER_TRANSITIONS = "/transitions"
MANAGER_METRICS = "/metrics"
