"""Throwaway hub for the Android Home device checks (docs/phase-51.md): a REAL in-process hub in front of a REAL companion-core, in-memory stores, nothing deployed.

    python clients/android/e2e/android_home_hub_server.py HUB_PORT [WEATHER_DOWN_FLAG_PATH]

Seeds an owner whose day has meetings, a busy-only event and an all-day banner (a calendar built around the current time, fed through the real feed service and downloader from a loopback
ICS server), open tasks (one confirmed from a meeting action, one sensitive that must never appear), reminders (overdue and today), one pending note proposal and one pending meeting
action. Weather comes from a scripted Open-Meteo transport; while the flag file exists the provider answers 503, so the weather card can be seen failing alone.

Owner login `owner` / `correct-password`. Reach it from the emulator with `adb reverse tcp:HUB_PORT tcp:HUB_PORT`. CALENDAR_FEED_ALLOW_LOCAL_FOR_TESTING is set here only; never set it anywhere else.
"""

import asyncio
import http.server
import importlib.util
import os
import sys
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def build_ics() -> str:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    stamp = lambda d: d.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")  # noqa: E731

    def vevent(uid, start, end, summary, *extra):
        return "\n".join(["BEGIN:VEVENT", f"UID:{uid}", "DTSTAMP:20261001T000000Z", f"DTSTART:{stamp(start)}", f"DTEND:{stamp(end)}", f"SUMMARY:{summary}", *extra, "END:VEVENT"])

    people = ("ATTENDEE;PARTSTAT=ACCEPTED:mailto:owner@example.com", "ATTENDEE;PARTSTAT=ACCEPTED:mailto:dev@example.com")
    hour = timedelta(hours=1)
    day = now.replace(hour=0, minute=0)
    events = [
        vevent("review@e2e", now + timedelta(minutes=20), now + timedelta(minutes=20) + hour, "Design review", *people),
        vevent("vendor@e2e", now + 2 * hour, now + 3 * hour, "Vendor sync", "LOCATION:https://example.zoom.us/j/1"),
        vevent("private@e2e", now + timedelta(minutes=45), now + timedelta(minutes=75), "Secret errand", "CLASS:PRIVATE", "LOCATION:Raffles Clinic"),
        vevent("dentist@e2e", now + 4 * hour, now + 5 * hour, "Dentist appointment"),
        "\n".join(["BEGIN:VEVENT", "UID:leave@e2e", "DTSTAMP:20261001T000000Z", f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{(day + timedelta(days=1)):%Y%m%d}", "SUMMARY:Team offsite", "END:VEVENT"]),
    ]
    return "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Reachy e2e//EN\n" + "\n".join(events) + "\nEND:VCALENDAR\n"


def serve_ics(port: int, body: str) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/calendar")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    threading.Thread(target=http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever, daemon=True).start()


async def serve(hub_port: int, flag: Path) -> None:
    os.environ["CALENDAR_FEED_ALLOW_LOCAL_FOR_TESTING"] = "1"
    os.environ["NOTEPAD_PROCESSING_ENABLED"] = "true"  # production has both on; the routes and services exist only with the flags
    os.environ["MEETING_ANALYSIS_ENABLED"] = "true"
    import httpx
    import uvicorn

    module = load("test_web_client", HERE.parents[2] / "services" / "reachy-hub" / "tests" / "test_web_client.py")
    from companion_core.calendar.feed import CalendarFeedService, InMemoryFeedStore, run_refresh_loop
    from companion_core.calendar.safe_fetch import FeedFetcher
    from companion_core.meeting_analysis.models import Evidence, Item, ItemKind, ItemStatus
    from companion_core.meeting_analysis.store import InMemoryMeetingAnalysisStore
    from companion_core.meetings.models import Meeting, MeetingJobStatus
    from companion_core.notepad_processing.models import Kind, Proposal
    from companion_core.notepad_processing.store import InMemoryNotepadStore
    from companion_core.weather import WeatherService
    from reachy_hub.companion_core_client import CompanionCoreClient
    from reachy_hub.enrollment_store import InMemoryEnrollmentStore
    from shared.models.persona import PersonaPatch
    from shared.models.response import Privacy

    ics_port = hub_port + 1
    serve_ics(ics_port, build_ics())

    persona = module.InMemoryPersonaStore()
    await persona.set(PersonaPatch(location="Singapore", timezone="Asia/Singapore"))
    feed = CalendarFeedService(InMemoryFeedStore(), FeedFetcher(allow_local=True), timezone=lambda: asyncio.sleep(0, "Asia/Singapore"))

    def provider(request: httpx.Request) -> httpx.Response:
        if flag.exists():
            return httpx.Response(503)
        if "geocoding" in request.url.host:
            return httpx.Response(200, json={"results": [{"name": "Singapore", "latitude": 1.29, "longitude": 103.85, "country": "Singapore"}]})
        today = datetime.now(UTC).astimezone().strftime("%Y-%m-%d")
        return httpx.Response(200, json={
            "current": {"time": f"{today}T{datetime.now(UTC).astimezone().strftime('%H:%M')}", "temperature_2m": 30.4, "apparent_temperature": 36.0, "relative_humidity_2m": 78, "precipitation": 0.4,
                        "weather_code": 61, "wind_speed_10m": 9.3, "is_day": 1},
            "daily": {"time": [today], "weather_code": [80], "temperature_2m_max": [32.1], "temperature_2m_min": [26.0], "precipitation_sum": [7.5], "precipitation_probability_max": [85],
                      "sunrise": [f"{today}T06:58"], "sunset": [f"{today}T18:55"]},
        })

    tasks, planner, meetings = module.InMemoryTaskStore(), module.InMemoryPlannerStore(), module.InMemoryMeetingStore()
    notepad_store, analysis_store = InMemoryNotepadStore(), InMemoryMeetingAnalysisStore()
    meeting = Meeting(id="m-e2e", title="Cluster migration", source_filename="a.wav", content_type="audio/wav", audio_path="/nonexistent", status=MeetingJobStatus.COMPLETE)
    meetings._meetings[meeting.id] = meeting
    now = datetime.now(UTC)
    await tasks.add_task("Write the quarterly report")
    confirmed = await tasks.add_task("Alice: Contact the vendor about licensing", record_id="b3d1c1f0-0000-4000-8000-000000000001")
    await tasks.add_task("Salary negotiation notes", sensitivity=Privacy.SENSITIVE)
    await planner.add_reminder("Pay the electricity bill", now - timedelta(hours=3))
    await planner.add_reminder("Call the bank", now + timedelta(hours=2))
    await planner.add_reminder("Renew passport", now + timedelta(days=3))
    note = await planner.add_note("Weekly planning", "Renew the lab certificate")
    p = Proposal(job_id="j", note_id=note.id, snapshot_hash="h", kind=Kind.TASK, text="Renew the lab certificate", evidence="Renew the lab certificate", span_start=0, span_end=25,
                 fingerprint="f1", sensitivity=Privacy.WORK_PRIVATE)
    notepad_store._proposals[p.id] = p
    seg = lambda t: Evidence(segment=0, start=0, end=1, quote=t)  # noqa: E731
    for text, status, rid in (("Update the migration schedule", ItemStatus.PENDING, None), ("Contact the vendor about licensing", ItemStatus.ACCEPTED, confirmed.id)):
        item = Item(run_id="r", meeting_id=meeting.id, transcript_hash="t", kind=ItemKind.ACTION, text=text, evidence=[seg(text)], status=status, fingerprint=f"f-{text}",
                    sensitivity=Privacy.WORK_PRIVATE, record_id=rid, record_kind="task" if rid else None, assignee="Hariz" if rid is None else None)
        analysis_store._items[item.id] = item

    core = module.create_core_app(
        calendar_store=module.InMemoryCalendarStore(), calendar_feed_service=feed, run_calendar_feed_loop=False, task_store=tasks, planner_store=planner, meeting_store=meetings,
        run_meeting_worker_task=False, memory_store=module.InMemoryMemoryStore(), rag_store=module.InMemoryDocumentStore(), email_store=module.InMemoryEmailStore(),
        confirmation_store=module.InMemoryConfirmationStore(), llm_settings_store=module.InMemoryLLMSettingsStore(), llm_usage_store=module.InMemoryLLMUsageStore(), persona_store=persona,
        search_settings_store=module.InMemorySearchSettingsStore(), run_email_dispatch_task=False, notepad_store=notepad_store, run_notepad_runner=False,
        meeting_analysis_store=analysis_store, run_meeting_analysis_runner=False, weather_service=WeatherService(transport=httpx.MockTransport(provider), cache_seconds=60))
    client = await asyncio.to_thread(
        module.make_client, companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core)), accounts_service_token="e2e-service",
        enrollment_store=InMemoryEnrollmentStore())
    client.cookies.clear()
    server = uvicorn.Server(uvicorn.Config(client.app, host="127.0.0.1", port=hub_port, log_level="warning"))
    print(f"hub on {hub_port}, ics on {ics_port}; weather down while {flag} exists", flush=True)
    loop_task = asyncio.create_task(run_refresh_loop(feed, tick_seconds=5.0))

    async def seed_feed():
        await asyncio.sleep(2)
        await feed.set_url(f"http://127.0.0.1:{ics_port}/work.ics")

    seeding = asyncio.create_task(seed_feed())
    try:
        await server.serve()
    finally:
        loop_task.cancel()
        seeding.cancel()


if __name__ == "__main__":
    asyncio.run(serve(int(sys.argv[1]), Path(sys.argv[2] if len(sys.argv) > 2 else Path(tempfile.gettempdir()) / "reachy-home-weather-down")))
