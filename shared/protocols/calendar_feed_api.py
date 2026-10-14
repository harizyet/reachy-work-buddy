"""Read-only calendar feed (ADR 0035). companion-core serves the CORE_* paths behind its service token; the hub proxies them for the OWNER SESSION only (cookie plus CSRF for every
change, no bearer-token path: the phone and the browser both sign in as the owner) under the HUB_* paths. The feed URL is accepted by the PUT and is never returned by anything."""

CORE_FEED = "/calendar/feed"  # GET: status and settings (never the URL). PUT {url?, config?}: set the URL and/or the settings. DELETE: forget the feed
CORE_FEED_REFRESH = "/calendar/feed/refresh"  # POST: download and parse now
CORE_OVERRIDES = "/calendar/overrides"  # PUT {key, classification}: the owner's classification of an occurrence or series. DELETE {key}: remove it
CORE_REMINDERS = "/calendar/meeting-reminders"  # GET ?hours=: the bounded set of recording reminders the phone schedules locally
CORE_EVENTS = "/calendar/events"  # GET ?start&end[&include_cancelled][&occupying]: events with their classification

HUB_FEED = "/calendar-feed"
HUB_FEED_REFRESH = "/calendar-feed/refresh"
HUB_OVERRIDES = "/calendar-feed/overrides"
HUB_REMINDERS = "/calendar-feed/reminders"
HUB_EVENTS = "/calendar-feed/events"

CLASSIFICATIONS = ("meeting", "personal_appointment", "leave_or_ooo", "all_day", "unknown_timed", "busy_private")

# The Calendar screens (Web and Android) read ONE revision through this: events plus the feed's status, from the same state.
CORE_SCHEDULE = "/calendar/schedule"  # GET ?start&end[&include_cancelled]: {generation, snapshot_revision, generated_at, feed, events}
CORE_UPLOAD = "/calendar/feed/upload"  # PUT raw ICS (header X-Filename optional): validate the whole file, then replace the source atomically
HUB_SCHEDULE = "/calendar-feed/schedule"
HUB_UPLOAD = "/calendar-feed/upload"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
