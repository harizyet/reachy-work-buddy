"""The HTTP surface: authentication, state, and how failures are reported."""

import pytest
from fastapi.testclient import TestClient
from model_manager.app import create_app

from shared.models.model_manager import ModelTier

T1, T2 = ModelTier.T1, ModelTier.T2
AUTH = {"Authorization": "Bearer secret"}


@pytest.fixture
def client(make_manager):
    manager = make_manager(restore_retries=0)
    with TestClient(create_app(manager, "secret")) as c:
        c.manager = manager
        for _ in range(100):  # the app reconciles in the background at startup; requests are refused until it is done
            if c.get("/state", headers=AUTH).status_code == 200:
                break
        yield c


def test_health_is_open_everything_else_needs_the_token(client) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    for method, path in (("get", "/state"), ("post", "/tier/restore"), ("get", "/transitions"), ("get", "/metrics")):
        assert getattr(client, method)(path).status_code == 401
    assert client.get("/state", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_state_activate_and_restore_round_trip(client) -> None:
    state = client.get("/state", headers=AUTH).json()
    assert state["state"] == "ready_t1" and state["served_model_name"] == "reachy-local"
    deep = client.post("/tier/activate", json={"tier": "t2", "lease_seconds": 600}, headers=AUTH).json()
    assert deep["state"] == "ready_t2" and deep["model"] == "Qwen/Qwen3-14B-AWQ" and deep["lease_expires_at"]
    again = client.post("/tier/activate", json={"tier": "t2"}, headers=AUTH)
    assert again.status_code == 200 and again.json()["state"] == "ready_t2"  # idempotent
    assert client.post("/tier/restore", headers=AUTH).json()["state"] == "ready_t1"
    history = client.get("/transitions", headers=AUTH).json()
    assert history[0]["kind"] == "restore_t1" and history[0]["outcome"] == "ok" and history[0]["duration_s"] >= 0
    assert client.get("/metrics", headers=AUTH).json()["swaps_to_t2"] == 1


def test_a_failed_deep_start_is_a_502_that_says_the_fast_tier_was_restored(client) -> None:
    runtime = client.manager._rt
    runtime.inject("wait", T2)
    response = client.post("/tier/activate", json={"tier": "t2"}, headers=AUTH)
    assert response.status_code == 502
    assert response.json()["detail"]["fast_tier_restored"] is True
    assert client.get("/state", headers=AUTH).json()["state"] == "ready_t1"


def test_a_failed_restore_is_a_503_and_failed_state_is_visible(client) -> None:
    client.post("/tier/activate", json={"tier": "t2"}, headers=AUTH)
    runtime = client.manager._rt
    runtime.inject("start", T1, times=None)
    response = client.post("/tier/restore", headers=AUTH)
    assert response.status_code == 503 and response.json()["detail"]["state"] == "failed"
    state = client.get("/state", headers=AUTH).json()
    assert state["state"] == "failed" and "could not restore" in state["last_error"]
    assert client.post("/tier/activate", json={"tier": "t2"}, headers=AUTH).status_code == 409


def test_bad_requests_are_rejected(client) -> None:
    assert client.post("/tier/activate", json={"tier": "t9"}, headers=AUTH).status_code == 422
    assert client.post("/tier/activate", json={"tier": "t2", "lease_seconds": -5}, headers=AUTH).status_code == 422
