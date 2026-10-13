# Phase 51: Home dashboard and daily briefing

Decision record: [ADR 0036](adr/0036-home-dashboard.md). Evidence: [verification record](verification/home-dashboard-2026-10-13.md). **Built locally on `feature/home-dashboard` (branched from `feature/ics-calendar-meeting-reminders` at `087f695`); nothing deployed, no APK released.**

## Scope

Home replaces the default landing screen of the web app and the Android app: schedule, reminders, open tasks, suggestions awaiting review, weather, quick actions and a "Brief me on today" action. It reads what Phases 18, 31,
49 and the calendar feed already store; it adds no records, schema, queue or scheduler and changes no Phase 31 extraction or frozen Phase 48 file. Out of scope: scheduled daily notifications, automatic spoken briefings, any write from Home.

## Interfaces

| Route | Where | Notes |
|---|---|---|
| `GET /home[?sections=schedule,tasks,reminders,reviews,weather]` | core (service token), hub (owner session) | the snapshot or named sections; constants in `shared/protocols/home_api.py` |
| `POST /home/brief {narrative?}` | core, hub (owner session plus CSRF) | deterministic lines, plus the local model's checked wording |

Code: `companion_core/home.py` (snapshot), `home_brief.py` (wording and checks), `home_routes.py`, `weather.py`, `briefing.home_items`; hub `reachy_hub/home.py`; web `features/home/`, `api/home.ts`; Android `data/Home.kt`,
`HomeCache.kt`, `ui/HomeScreen.kt`, `data/Navigation.kt`. Section shape and statuses are in the ADR; the snapshot field list is in `home.py`'s docstrings and `api/home.ts`.

## Configuration

`WEATHER_ENABLED` (default true), `WEATHER_CACHE_MINUTES`, `WEATHER_TIMEOUT_SECONDS`, `WEATHER_STALE_HOURS`, `WEATHER_LATITUDE`/`WEATHER_LONGITUDE` (skip the place-name lookup), `WEATHER_FORECAST_URL`/`WEATHER_GEOCODE_URL`
(tests). The location and timezone are the persona's (Settings > Assistant). The reviews section needs `NOTEPAD_PROCESSING_ENABLED` and `MEETING_ANALYSIS_ENABLED`; off, it says so.

## Open for the owner

Browser check of Home and System; physical-phone check of Home (five tabs, tap-through, offline copy, recording while on Home); the weather location in Settings; then separately, approval to deploy core and hub and to release an APK (0.19.0 in the working tree).
