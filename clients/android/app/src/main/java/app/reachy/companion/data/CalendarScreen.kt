package app.reachy.companion.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.YearMonth
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/*
 * The Calendar screen (ADR 0035). It reads ONE revision from the hub (`GET /calendar-feed/schedule`: the events and the feed's status come from the same state) and keeps the last
 * answer on the phone, so it still shows something offline and says so. Everything it decides is here, pure: the month grid, which events fall on a day (in the phone's time zone),
 * their order, what a time and a reminder status say, and the sync lines, so it can be tested on the JVM.
 */

/** What the schedule route returns. [generation] is the calendar revision both the phone and the web read. */
@Serializable
data class ScheduleView(
    val generation: Long = 0,
    @SerialName("snapshot_revision") val snapshotRevision: String? = null,
    @SerialName("generated_at") val generatedAt: String = "",
    val feed: FeedBrief = FeedBrief(),
    val events: List<CalendarItem> = emptyList(),
)

/** The six Monday-first weeks that show [month], as 42 consecutive dates. */
fun monthGrid(month: YearMonth): List<LocalDate> {
    val first = month.atDay(1)
    val lead = first.dayOfWeek.value - 1
    return List(42) { first.plusDays((it - lead).toLong()) }
}

private fun start(item: CalendarItem, zone: ZoneId) = OffsetDateTime.parse(item.start).atZoneSameInstant(zone)
private fun end(item: CalendarItem, zone: ZoneId) = OffsetDateTime.parse(item.end).atZoneSameInstant(zone)

/** Whether the event touches the local [day]. An all-day event's end is exclusive, so one ending at midnight does not touch the day it ends on. */
fun onDay(item: CalendarItem, day: LocalDate, zone: ZoneId): Boolean {
    val from = day.atStartOfDay(zone).toInstant()
    val next = day.plusDays(1).atStartOfDay(zone).toInstant()
    val s = start(item, zone).toInstant()
    val e = end(item, zone).toInstant()
    return s < next && (e > from || (e == s && s >= from))
}

/** Cancelled and declined events are not on the owner's schedule. */
fun listed(items: List<CalendarItem>): List<CalendarItem> = items.filter { onSchedule(it) }

fun chronological(items: List<CalendarItem>, zone: ZoneId = ZoneId.systemDefault()): List<CalendarItem> =
    items.sortedWith(compareBy({ start(it, zone).toInstant() }, { end(it, zone).toInstant() }, { it.title }))

fun eventsOn(items: List<CalendarItem>, day: LocalDate, zone: ZoneId = ZoneId.systemDefault()): List<CalendarItem> =
    chronological(listed(items).filter { onDay(it, day, zone) }, zone)

enum class Marker { Meeting, Leave, Other }

/** What a day in the grid is marked with: a dot for a meeting, a square for leave, a ring for anything else. */
fun dayMarkers(items: List<CalendarItem>, day: LocalDate, zone: ZoneId = ZoneId.systemDefault()): List<Marker> {
    val here = eventsOn(items, day, zone)
    return buildList {
        if (here.any { it.classification == "meeting" }) add(Marker.Meeting)
        if (here.any { it.classification == "leave_or_ooo" }) add(Marker.Leave)
        if (here.any { it.classification != "meeting" && it.classification != "leave_or_ooo" }) add(Marker.Other)
    }
}

private val DAY = DateTimeFormatter.ofPattern("EEE d MMM")
private val CLOCK = DateTimeFormatter.ofPattern("HH:mm")

/** The time of an event on [day] in the phone's zone: clock times for a timed one (Busy entries too), the days covered for an all-day one. */
fun dayTime(item: CalendarItem, day: LocalDate, zone: ZoneId = ZoneId.systemDefault()): String {
    val s = start(item, zone)
    val e = end(item, zone)
    if (item.allDay) {
        val last = e.toLocalDate().minusDays(1)
        return if (!last.isAfter(s.toLocalDate())) "All day" else "All day, ${DAY.format(s)} to ${DAY.format(last)}"
    }
    val lead = if (s.toLocalDate() != day) "${DAY.format(s)} " else ""
    if (!e.isAfter(s)) return lead + CLOCK.format(s)
    val tail = if (e.toLocalDate() != s.toLocalDate()) "${DAY.format(e)} " else ""
    return "$lead${CLOCK.format(s)}–$tail${CLOCK.format(e)}"
}

/** Whether a recording reminder is set, and if not why, in words (the same wording as the web). */
fun reminderStatus(item: CalendarItem): String = when {
    item.remind -> "Recording reminder on"
    item.remindBlocked == "declined" -> "No reminder: declined"
    item.remindBlocked == "cancelled" -> "No reminder: cancelled"
    item.remindBlocked == "all_day" -> "No reminder: all-day"
    item.remindBlocked == "on_leave" -> "No reminder: you are on leave"
    item.remindBlocked == "unconfirmed_meeting" -> "No reminder: not confirmed as a meeting"
    item.classification == "busy_private" -> "No reminder: details hidden"
    item.classification == "leave_or_ooo" -> "No reminder: leave"
    item.classification == "personal_appointment" -> "No reminder: personal appointment"
    item.classification == "unknown_timed" -> "No reminder: could not tell it is a meeting"
    else -> "No reminder"
}

/** The next meetings, soonest first: classified as meetings, not yet finished, not cancelled or declined. */
fun upcomingMeetings(items: List<CalendarItem>, nowMs: Long, zone: ZoneId = ZoneId.systemDefault(), limit: Int = 5): List<CalendarItem> =
    chronological(listed(items).filter { it.classification == "meeting" && end(it, zone).toInstant().toEpochMilli() > nowMs }, zone).take(limit)

fun ago(iso: String?, nowMs: Long): String {
    val at = iso?.let { runCatching { millis(it) }.getOrNull() } ?: return "never"
    val s = ((nowMs - at) / 1000).coerceAtLeast(0)
    return when {
        s < 60 -> "just now"
        s < 3600 -> "${(s + 30) / 60} min ago"
        s < 86_400 -> "${(s + 1800) / 3600} h ago"
        else -> "${(s + 43_200) / 86_400} d ago"
    }
}

fun syncStateText(feed: FeedBrief): String = when (feed.syncState ?: feed.freshness) {
    "not_configured" -> "No calendar set up"
    "never" -> "Not loaded yet"
    "refreshing" -> "Refreshing"
    "ok", "fresh" -> "Up to date"
    "error" -> "Last refresh failed; showing the last good copy"
    "stale" -> "Out of date"
    else -> "Unknown"
}

/** The host of a link or the name of an uploaded file; the path of a link is a secret and never reaches the phone. */
fun sourceText(feed: FeedBrief): String = when {
    !feed.configured -> "None"
    feed.source == "upload" -> "Uploaded file" + (feed.host?.let { " ($it)" } ?: "")
    else -> "Calendar link" + (feed.host?.let { " ($it)" } ?: "")
}

fun errorText(code: String?): String? = when {
    code == null -> null
    code == "timeout" -> "The calendar server took too long to answer."
    code == "connect_failed" -> "The calendar server could not be reached."
    code == "dns_failed" -> "The address could not be looked up."
    code == "not_calendar" -> "The source did not return a calendar."
    code == "too_large" -> "The calendar is larger than the 10 MB limit."
    code == "parse_failed" -> "The calendar could not be read."
    code == "unsafe_url" || code == "unsafe_address" || code == "redirect_refused" -> "The address is not allowed."
    code.startsWith("http_") -> "The calendar server answered ${code.removePrefix("http_")}."
    else -> "The calendar could not be loaded."
}

/** Whether what is on screen is a saved copy: the phone could not reach the hub, or the hub's last refresh failed or is old. */
fun isCached(feed: FeedBrief, offline: Boolean): Boolean = offline || feed.syncState == "error" || feed.syncState == "stale" || feed.freshness == "stale"

/** The sync lines of the screen. The source's last successful refresh (server clock) and the phone's last successful check of the hub are separate facts. */
data class SyncLine(val label: String, val value: String)

fun syncLines(view: ScheduleView, lastCheckedMs: Long?, offline: Boolean, nowMs: Long): List<SyncLine> {
    val feed = view.feed
    val cached = isCached(feed, offline)
    return buildList {
        add(SyncLine("State", syncStateText(feed) + if (cached) " (cached)" else ""))
        add(SyncLine("Source", sourceText(feed)))
        add(SyncLine("Source last refreshed", feed.lastSuccessAt?.let { "${DAY.format(OffsetDateTime.parse(it).toInstant().atZone(ZoneId.systemDefault()))} ${CLOCK.format(OffsetDateTime.parse(it).toInstant().atZone(ZoneId.systemDefault()))} (${ago(it, nowMs)})" } ?: "never"))
        add(SyncLine("Phone last checked the hub", lastCheckedMs?.let { "${CLOCK.format(Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()))} (${ago(Instant.ofEpochMilli(it).toString(), nowMs)})" } ?: "never"))
        add(SyncLine("Events", feed.eventCount.toString()))
        add(SyncLine("Revision", view.generation.toString()))
        errorText(feed.error)?.let { add(SyncLine("Last error", it)) }
        if (offline) add(SyncLine("Hub", "Not reachable; showing the copy saved on this phone"))
    }
}
