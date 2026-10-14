"""Throwaway hub for the Android meeting-reminder device checks (ADR 0035): a REAL in-process hub in front of a REAL companion-core whose calendar feed is the real service with the real
downloader, pointed at a local ICS file served over plain HTTP on loopback. Stores are in memory; nothing here is a deployment.

    python clients/android/e2e/android_calendar_hub_server.py gen ICS_PATH initial|changed     # write a calendar built around the current time
    python clients/android/e2e/android_calendar_hub_server.py serve HUB_PORT ICS_PORT ICS_PATH   # run the hub (HUB_PORT) and the ICS server (ICS_PORT)

Owner login `owner` / `correct-password`. Reach the hub from the emulator with `adb reverse tcp:HUB_PORT tcp:HUB_PORT`. In the app's hub, set the feed with
PUT /calendar-feed {"url": "http://127.0.0.1:ICS_PORT/work.ics"}: the local address is refused in production and accepted here only because this script sets
CALENDAR_FEED_ALLOW_LOCAL_FOR_TESTING=1 (never set it anywhere else).
"""

import asyncio
import http.server
import importlib.util
import os
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def vevent(uid, start, end, summary=None, *extra):
    lines = ["BEGIN:VEVENT", f"UID:{uid}", "DTSTAMP:20261001T000000Z", f"DTSTART:{stamp(start)}", f"DTEND:{stamp(end)}"]
    if summary:
        lines.append(f"SUMMARY:{summary}")
    return "\n".join([*lines, *extra, "END:VEVENT"])


def build_calendar(scenario: str) -> str:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    people = ("ATTENDEE;PARTSTAT=ACCEPTED:mailto:owner@example.com", "ATTENDEE;PARTSTAT=ACCEPTED:mailto:dev@example.com")
    hour = timedelta(hours=1)
    day = now.replace(hour=0, minute=0)
    events = []
    if scenario == "initial":
        events += [
            vevent("review@e2e", now + timedelta(minutes=7), now + timedelta(minutes=7) + hour, "Design review", *people),
            vevent("vendor@e2e", now + hour, now + 2 * hour, "Vendor sync", "LOCATION:https://example.zoom.us/j/1"),
        ]
    else:  # changed: the review moves later, the vendor sync is cancelled, a new meeting is added
        events += [
            vevent("review@e2e", now + timedelta(minutes=14), now + timedelta(minutes=14) + hour, "Design review", "SEQUENCE:1", *people),
            vevent("vendor@e2e", now + hour, now + 2 * hour, "Vendor sync", "STATUS:CANCELLED", "SEQUENCE:1", "LOCATION:https://example.zoom.us/j/1"),
            vevent("late@e2e", now + timedelta(minutes=20), now + timedelta(minutes=50), "Late addition", *people),
        ]
    events += [
        vevent("quiet@e2e", now + timedelta(minutes=30), now + timedelta(minutes=60), "Quiet block"),
        vevent("dentist@e2e", now + timedelta(minutes=90), now + timedelta(minutes=150), "Dentist appointment"),
        vevent("private@e2e", now + timedelta(minutes=45), now + timedelta(minutes=75), "Secret errand", "CLASS:PRIVATE"),
        vevent("cancelled@e2e", now + timedelta(minutes=20), now + timedelta(minutes=50), "Cancelled planning meeting", "STATUS:CANCELLED", *people),
        "\n".join(["BEGIN:VEVENT", "UID:leave@e2e", "DTSTAMP:20261001T000000Z", f"DTSTART;VALUE=DATE:{(day + timedelta(days=1)):%Y%m%d}",
                   f"DTEND;VALUE=DATE:{(day + timedelta(days=3)):%Y%m%d}", "SUMMARY:Annual leave", "END:VEVENT"]),
    ]
    return "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Reachy e2e//EN\n" + "\n".join(events) + "\nEND:VCALENDAR\n"


def serve_ics(port: int, path: Path) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/calendar")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    threading.Thread(target=http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever, daemon=True).start()


async def serve(hub_port: int, ics_port: int, ics_path: Path) -> None:
    os.environ["CALENDAR_FEED_ALLOW_LOCAL_FOR_TESTING"] = "1"
    import httpx
    import uvicorn

    tests = Path(__file__).resolve().parents[3] / "services" / "reachy-hub" / "tests" / "test_web_client.py"
    spec = importlib.util.spec_from_file_location("test_web_client", tests)
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_web_client"] = module
    spec.loader.exec_module(module)
    from companion_core.calendar.feed import CalendarFeedService, InMemoryFeedStore, run_refresh_loop
    from companion_core.calendar.safe_fetch import FeedFetcher
    from reachy_hub.companion_core_client import CompanionCoreClient
    from reachy_hub.enrollment_store import InMemoryEnrollmentStore

    serve_ics(ics_port, ics_path)
    persona_zone = "Asia/Singapore"

    async def zone():
        return persona_zone

    feed = CalendarFeedService(InMemoryFeedStore(), FeedFetcher(allow_local=True), timezone=zone)
    core = module.create_core_app(
        calendar_store=module.InMemoryCalendarStore(), calendar_feed_service=feed, run_calendar_feed_loop=False, task_store=module.InMemoryTaskStore(),
        planner_store=module.InMemoryPlannerStore(), meeting_store=module.InMemoryMeetingStore(), run_meeting_worker_task=False, memory_store=module.InMemoryMemoryStore(),
        rag_store=module.InMemoryDocumentStore(), email_store=module.InMemoryEmailStore(), confirmation_store=module.InMemoryConfirmationStore(),
        llm_settings_store=module.InMemoryLLMSettingsStore(), llm_usage_store=module.InMemoryLLMUsageStore(), persona_store=module.InMemoryPersonaStore(),
        search_settings_store=module.InMemorySearchSettingsStore(), run_email_dispatch_task=False)
    client = await asyncio.to_thread(
        module.make_client, companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core)), accounts_service_token="e2e-service",
        enrollment_store=InMemoryEnrollmentStore())
    client.cookies.clear()
    server = uvicorn.Server(uvicorn.Config(client.app, host="127.0.0.1", port=hub_port, log_level="warning"))
    loop_task = asyncio.create_task(run_refresh_loop(feed, tick_seconds=5.0))  # the real refresh loop, as core's lifespan would run it
    print(f"hub on {hub_port}, ics on {ics_port} ({ics_path})", flush=True)
    try:
        await server.serve()
    finally:
        loop_task.cancel()


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        Path(sys.argv[2]).write_text(build_calendar(sys.argv[3]))
    else:
        asyncio.run(serve(int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])))
