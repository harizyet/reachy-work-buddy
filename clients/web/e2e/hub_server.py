"""Real in-process hub for the Playwright suite: the production hub app with in-memory stores,
one registered simulated robot, and the owner login `owner` / `correct-password`. It serves
whatever clients/web/dist holds, so run `npm run build` first. Test fixture only; never a deployment.

    python e2e/hub_server.py PORT
"""

import importlib.util
import sys
from pathlib import Path

import uvicorn

tests = Path(__file__).resolve().parents[3] / "services" / "reachy-hub" / "tests" / "test_web_client.py"
spec = importlib.util.spec_from_file_location("test_web_client", tests)
module = importlib.util.module_from_spec(spec)
sys.modules["test_web_client"] = module
spec.loader.exec_module(module)

if __name__ == "__main__":
    # Owner-bound, as deployed: the chat is fixed to the owner and private routes need the owner session.
    from reachy_hub.enrollment_store import InMemoryEnrollmentStore

    client = module.logged_in_client(accounts_service_token="e2e-service", enrollment_store=InMemoryEnrollmentStore())
    client.cookies.clear()
    uvicorn.run(client.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
