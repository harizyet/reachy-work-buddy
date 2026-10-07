"""model-manager server and a small owner CLI.

    python -m model_manager serve [--host H]           # default loopback; MODEL_MANAGER_TOKEN required
    python -m model_manager state | activate t2 [--lease S] | restore | transitions
    python -m model_manager run [--lease S] -- COMMAND  # deep tier for one command, tier 1 restored afterwards
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import httpx
import uvicorn

from model_manager.app import create_app
from model_manager.config import load_config
from model_manager.machine import ModelManager
from model_manager.runtime import DockerRuntime

DEFAULT_URL = "http://127.0.0.1:8090"


def serve(port: int, host: str) -> None:
    token = os.environ.get("MODEL_MANAGER_TOKEN")
    if not token:
        sys.exit("MODEL_MANAGER_TOKEN is not set; refusing to start an unauthenticated manager")
    config = load_config()
    app = create_app(ModelManager(DockerRuntime(config), config), token)
    uvicorn.run(app, host=host, port=port, log_level="info")


def _call(args, method: str, path: str, **kwargs) -> httpx.Response:
    token = os.environ.get("MODEL_MANAGER_TOKEN", "")
    return httpx.request(method, args.url + path, headers={"Authorization": f"Bearer {token}"}, timeout=1800, **kwargs)


def _show(response: httpx.Response) -> int:
    print(json.dumps(response.json(), indent=1))
    return 0 if response.is_success else 1


def run_command(args) -> int:
    """Deep tier for the duration of one command. Tier 1 is restored even if the command fails or is interrupted."""
    activated = _call(args, "POST", "/tier/activate", json={"tier": "t2", "lease_seconds": args.lease})
    if not activated.is_success:
        print("could not switch to the deep tier:", activated.text, file=sys.stderr)
        return 1
    code = 1
    try:
        code = subprocess.call(args.command)
    finally:
        restored = _call(args, "POST", "/tier/restore")
        if not restored.is_success:
            print("FAST TIER NOT RESTORED:", restored.text, file=sys.stderr)
            code = code or 2
    return code


def main() -> int:
    parser = argparse.ArgumentParser(prog="model_manager")
    parser.add_argument("--url", default=os.environ.get("MODEL_MANAGER_URL", DEFAULT_URL))
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve_p = sub.add_parser("serve")
    serve_p.add_argument("--port", type=int, default=8090)
    serve_p.add_argument("--host", default=os.environ.get("MODEL_MANAGER_HOST", "127.0.0.1"))
    sub.add_parser("state")
    sub.add_parser("restore")
    sub.add_parser("transitions")
    act = sub.add_parser("activate")
    act.add_argument("tier", choices=["t1", "t2"])
    act.add_argument("--lease", type=float)
    run = sub.add_parser("run")
    run.add_argument("--lease", type=float)
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.cmd == "serve":
        serve(args.port, args.host)
        return 0
    if args.cmd == "state":
        return _show(_call(args, "GET", "/state"))
    if args.cmd == "restore":
        return _show(_call(args, "POST", "/tier/restore"))
    if args.cmd == "transitions":
        return _show(_call(args, "GET", "/transitions"))
    if args.cmd == "activate":
        return _show(_call(args, "POST", "/tier/activate", json={"tier": args.tier, "lease_seconds": args.lease}))
    args.command = [c for c in args.command if c != "--"]
    if not args.command:
        parser.error("run needs a command after --")
    return run_command(args)


if __name__ == "__main__":
    sys.exit(main())
