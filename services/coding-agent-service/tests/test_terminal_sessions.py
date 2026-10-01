"""Terminal (non-Reachy) Claude Code sessions are listed read-only from a
mounted history directory."""

from __future__ import annotations

import json
import os
import time

from coding_agent_service.app import create_app
from coding_agent_service.terminal_sessions import list_terminal_sessions
from fastapi.testclient import TestClient

from shared.protocols.coding_agent import SERVICE_HEADER, TERMINAL_SESSIONS


def _write(root, project, session, entries, age=0):
    folder = root / project
    folder.mkdir(exist_ok=True)
    path = folder / f"{session}.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))


def test_lists_newest_first_with_title_prompt_and_activity(tmp_path) -> None:
    _write(
        tmp_path,
        "-home-me-app",
        "aaa",
        [
            {
                "type": "user",
                "isMeta": True,
                "message": {"content": "meta"},
                "cwd": "/home/me/app",
            },
            {"type": "user", "message": {"content": "<command-name>/x</command-name>"}},
            {
                "type": "user",
                "message": {"content": "Fix the login bug"},
                "cwd": "/home/me/app",
                "gitBranch": "fix",
            },
            {"type": "last-prompt", "lastPrompt": "now add tests"},
        ],
        age=10,
    )
    _write(
        tmp_path,
        "-home-me-old",
        "bbb",
        [{"type": "custom-title", "customTitle": "Old work"}],
        age=3600,
    )
    (tmp_path / "-home-me-app" / "broken.jsonl").write_text("not json\n")
    sessions = list_terminal_sessions(tmp_path)
    by_id = {s.session_id: s for s in sessions}
    assert by_id["aaa"].title == "Fix the login bug"
    assert by_id["aaa"].last_prompt == "now add tests"
    assert (
        by_id["aaa"].project_path,
        by_id["aaa"].git_branch,
        by_id["aaa"].active,
    ) == ("/home/me/app", "fix", True)
    assert by_id["bbb"].title == "Old work" and by_id["bbb"].active is False
    assert sessions[-1].session_id == "bbb"


def test_missing_directory_is_an_empty_list_and_route_needs_the_token(tmp_path) -> None:
    assert list_terminal_sessions(None) == []
    assert list_terminal_sessions(tmp_path / "absent") == []
    _write(tmp_path, "-p", "ccc", [{"type": "user", "message": {"content": "hello"}}])
    client = TestClient(create_app(service_token="tok", terminal_sessions_dir=tmp_path))
    assert client.get(TERMINAL_SESSIONS).status_code == 401
    body = client.get(TERMINAL_SESSIONS, headers={SERVICE_HEADER: "tok"}).json()
    assert [s["session_id"] for s in body] == ["ccc"]
