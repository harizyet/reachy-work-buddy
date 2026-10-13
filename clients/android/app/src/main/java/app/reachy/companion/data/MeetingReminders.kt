package app.reachy.companion.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/*
 * Meeting recording reminders (ADR 0035). The hub gives the phone a bounded set of reminders (the next 72 hours by default); the phone schedules each one locally so it
 * arrives without a network, and re-arms them after a restart. Everything in this file is pure so it can be tested on the JVM: what to schedule, what to cancel, what a
 * notification says, whether a recording may be started, and what is wrong when reminders will not arrive.
 */

/** One recording reminder as the hub returns it. [title] is null when the calendar gave none or hid it: the phone never makes one up. */
@Serializable
data class MeetingReminder(
    @SerialName("event_key") val eventKey: String,
    @SerialName("series_key") val seriesKey: String = "",
    val revision: String = "",
    val title: String? = null,
    val start: String,
    val end: String,
    @SerialName("notify_at") val notifyAt: String,
    @SerialName("lead_minutes") val leadMinutes: Int = 5,
    val classification: String = "meeting",
    val basis: String = "explicit",
    val recurring: Boolean = false,
)

@Serializable
data class FeedBrief(
    val configured: Boolean = false,
    val freshness: String = "never",
    @SerialName("age_seconds") val ageSeconds: Long? = null,
    val error: String? = null,
    val host: String? = null,
    val source: String? = null,
    @SerialName("sync_state") val syncState: String? = null,
    @SerialName("last_success_at") val lastSuccessAt: String? = null,
    @SerialName("last_attempt_at") val lastAttemptAt: String? = null,
    @SerialName("event_count") val eventCount: Int = 0,
    val generation: Long = 0,
    @SerialName("snapshot_revision") val snapshotRevision: String? = null,
)

@Serializable
data class ReminderSet(
    @SerialName("generated_at") val generatedAt: String,
    @SerialName("horizon_end") val horizonEnd: String = "",
    @SerialName("lead_minutes") val leadMinutes: Int = 5,
    @SerialName("snapshot_revision") val snapshotRevision: String? = null,
    val feed: FeedBrief = FeedBrief(),
    val reminders: List<MeetingReminder> = emptyList(),
)

fun millis(iso: String): Long = OffsetDateTime.parse(iso).toInstant().toEpochMilli()

/** A reminder that is due to be scheduled on this phone. [fireAtMs] is when it notifies; [startMs] when the meeting starts. */
data class PlannedReminder(val reminder: MeetingReminder, val startMs: Long, val fireAtMs: Long, val late: Boolean) {
    val key get() = reminder.eventKey
    /** One notification per occurrence and start time: the same occurrence moved to a new time is a new reminder, the same time seen again is not. */
    val firedKey get() = firedKey(reminder.eventKey, startMs)
}

fun firedKey(eventKey: String, startMs: Long) = "$eventKey@$startMs"

const val MAX_SCHEDULED = 64
private const val LATE_FIRE_DELAY_MS = 1_000L

/**
 * What to schedule from the hub's set. Skipped: a meeting that has already started, a reminder already shown or dismissed for that start time, anything the hub did not
 * classify as a meeting (the hub already filters; this is a second guard), and a repeated key. A reminder whose time has passed but whose meeting has not started notifies
 * at once, once. At most [MAX_SCHEDULED] are scheduled, the earliest first.
 */
fun planReminders(set: ReminderSet, nowMs: Long, fired: Set<String>): List<PlannedReminder> {
    val seen = HashSet<String>()
    val planned = ArrayList<PlannedReminder>()
    for (reminder in set.reminders) {
        if (reminder.classification != "meeting" || !seen.add(reminder.eventKey)) continue
        val start = runCatching { millis(reminder.start) }.getOrNull() ?: continue
        val notify = runCatching { millis(reminder.notifyAt) }.getOrNull() ?: continue
        if (start <= nowMs || firedKey(reminder.eventKey, start) in fired) continue
        val late = notify <= nowMs
        planned += PlannedReminder(reminder, start, if (late) nowMs + LATE_FIRE_DELAY_MS else notify, late)
    }
    return planned.sortedWith(compareBy({ it.fireAtMs }, { it.key })).take(MAX_SCHEDULED)
}

data class Reconciliation(val cancel: Set<String>, val schedule: List<PlannedReminder>)

/**
 * Compares what is armed ([armed]: key to fire time) with what should be. A reminder no longer wanted (the meeting was cancelled, declined, removed or reclassified) is
 * cancelled; one that is new or whose time changed (the meeting was moved) is scheduled again; one unchanged is left alone unless [rearmAll] (after a restart, which clears
 * every alarm).
 */
fun reconcile(armed: Map<String, Long>, planned: List<PlannedReminder>, rearmAll: Boolean = false): Reconciliation {
    val wanted = planned.associateBy { it.key }
    return Reconciliation(
        cancel = armed.keys - wanted.keys,
        schedule = planned.filter { rearmAll || armed[it.key] != it.fireAtMs },
    )
}

/** Entries older than a day are forgotten, so the record does not grow for ever. */
fun pruneFired(fired: Set<String>, nowMs: Long): Set<String> =
    fired.filter { (it.substringAfterLast('@', "").toLongOrNull() ?: 0L) > nowMs - 24 * 3_600_000L }.toSet()

// --- what the notification says --------------------------------------------------------------------------------------------------------------------------

fun reminderTitle(title: String?): String = title?.trim()?.takeIf { it.isNotEmpty() } ?: "Meeting"

fun minutesUntil(startMs: Long, nowMs: Long): Long = ((startMs - nowMs) + 59_999L).coerceAtLeast(0L) / 60_000L

fun reminderText(startMs: Long, nowMs: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val minutes = minutesUntil(startMs, nowMs)
    val at = DateTimeFormatter.ofPattern("HH:mm").format(Instant.ofEpochMilli(startMs).atZone(zone))
    return when {
        minutes <= 0L -> "Starting now · $at"
        minutes == 1L -> "Starts in 1 minute · $at"
        else -> "Starts in $minutes minutes · $at"
    }
}

// --- opening the recorder from a reminder ---------------------------------------------------------------------------------------------------------------

/** What the notification's "Start recording" hands to the app. It only prepares the recorder; nothing records until the owner taps Record. */
data class PreparedMeeting(val key: String, val title: String?, val startMs: Long)

private const val MAX_TITLE = 200
private const val MAX_KEY = 100

/** Validates what an intent carries (the activity can be started by other apps): a feed key, a bounded title, a sane time. Null when it is not acceptable. */
fun preparedFrom(key: String?, title: String?, startMs: Long, nowMs: Long): PreparedMeeting? {
    if (key == null || !key.startsWith("ics:") || key.length > MAX_KEY) return null
    if (startMs <= 0L || kotlin.math.abs(startMs - nowMs) > 30L * 24 * 3_600_000L) return null
    return PreparedMeeting(key, title?.trim()?.take(MAX_TITLE)?.takeIf { it.isNotEmpty() }, startMs)
}

/** The recording's title: the calendar's, or when the calendar gave none, the same dated default the recorder already uses. */
fun recordingTitle(prepared: PreparedMeeting, zone: ZoneId = ZoneId.systemDefault()): String =
    prepared.title ?: ("Meeting " + DateTimeFormatter.ofPattern("d MMM HH:mm").format(Instant.ofEpochMilli(prepared.startMs).atZone(zone)))

fun scheduledText(startMs: Long, zone: ZoneId = ZoneId.systemDefault()): String =
    "Scheduled " + DateTimeFormatter.ofPattern("EEE d MMM, HH:mm").format(Instant.ofEpochMilli(startMs).atZone(zone))

/** Whether a recording may be started for a prepared meeting. A second tap, a second notification or a recording already waiting never makes a second record. */
sealed interface RecordingGate {
    data object Ready : RecordingGate
    data class AlreadyRecorded(val meetingId: String) : RecordingGate
    data object WaitingToUpload : RecordingGate
    data object RecordingThis : RecordingGate
    data object RecordingSomethingElse : RecordingGate
}

fun recordingGate(
    prepared: PreparedMeeting, recorded: Map<String, String>, pendingKeys: Set<String>, recording: Boolean, recordingKey: String?,
): RecordingGate = when {
    recording && recordingKey == prepared.key -> RecordingGate.RecordingThis
    recording -> RecordingGate.RecordingSomethingElse
    prepared.key in recorded -> RecordingGate.AlreadyRecorded(recorded.getValue(prepared.key))
    prepared.key in pendingKeys -> RecordingGate.WaitingToUpload
    else -> RecordingGate.Ready
}

/** The note kept beside a recording until it is uploaded, so the title and the calendar identity follow the file even if the app is restarted. */
@Serializable
data class RecordingPlan(val key: String, val title: String? = null, val startMs: Long)

private val planJson = Json { ignoreUnknownKeys = true }
fun encodePlan(plan: RecordingPlan): String = planJson.encodeToString(plan)
fun decodePlan(text: String): RecordingPlan? = runCatching { planJson.decodeFromString<RecordingPlan>(text) }.getOrNull()

// --- is the phone able to deliver them ---------------------------------------------------------------------------------------------------------------------------

/** What is wrong, worst first. The app shows the first as a short line; none means reminders should arrive. */
enum class ReminderIssue(val text: String) {
    Off("Meeting reminders are off."),
    NotificationsBlocked("Notifications are off for Reachy, so meeting reminders cannot show. Turn them on in the phone's settings."),
    ChannelBlocked("The Meeting reminders notification category is off in the phone's settings."),
    NeverSynced("Meeting reminders have not been loaded yet. Open the app with a connection to the hub."),
    HubUnreachable("The hub could not be reached, so reminders may be out of date. The ones already loaded still work."),
    FeedNotSet("No calendar feed is set up. Add it in the web control panel."),
    FeedStale("The calendar feed has not refreshed recently, so reminders may be out of date."),
    FeedError("The calendar feed could not be read. Reminders already loaded still work."),
    ApproximateTimes("The phone does not allow exact alarms, so reminders may arrive a little late."),
}

fun reminderIssues(
    enabled: Boolean, notificationsAllowed: Boolean, channelAllowed: Boolean, exactAllowed: Boolean, set: ReminderSet?, lastSyncFailed: Boolean,
): List<ReminderIssue> {
    if (!enabled) return listOf(ReminderIssue.Off)
    val issues = ArrayList<ReminderIssue>()
    if (!notificationsAllowed) issues += ReminderIssue.NotificationsBlocked
    else if (!channelAllowed) issues += ReminderIssue.ChannelBlocked
    if (set == null) issues += ReminderIssue.NeverSynced
    if (lastSyncFailed && set != null) issues += ReminderIssue.HubUnreachable
    if (set != null && !set.feed.configured) issues += ReminderIssue.FeedNotSet
    else if (set != null && set.feed.error != null) issues += ReminderIssue.FeedError
    else if (set != null && set.feed.freshness == "stale") issues += ReminderIssue.FeedStale
    if (!exactAllowed) issues += ReminderIssue.ApproximateTimes
    return issues
}

// --- the schedule list (the same classification as the web) ---------------------------------------------------------------------------------------------

/** One calendar event as `GET /calendar-feed/events` returns it. The hub's classification is shown as is; the phone never classifies anything itself. */
@Serializable
data class CalendarItem(
    val title: String,
    val start: String,
    val end: String,
    val location: String? = null,
    @SerialName("all_day") val allDay: Boolean = false,
    val classification: String? = null,
    @SerialName("classification_basis") val basis: String? = null,
    val status: String = "confirmed",
    val response: String? = null,
    val redacted: Boolean = false,
    @SerialName("title_missing") val titleMissing: Boolean = false,
    val source: String = "local",
    @SerialName("event_key") val eventKey: String? = null,
    val remind: Boolean = false,
    @SerialName("remind_blocked") val remindBlocked: String? = null,
)

fun classLabel(item: CalendarItem): String = when (item.classification) {
    "meeting" -> "Meeting"
    "personal_appointment" -> "Appointment"
    "leave_or_ooo" -> "Leave"
    "all_day" -> "All day"
    "busy_private" -> "Busy"
    "unknown_timed" -> "Timed event"
    else -> "Event"
}

/** What the owner sees for the time: the clock time of a timed event, or the days of an all-day one. An all-day event's end is exclusive, so a three-day leave from the 19th ends on the 21st. */
fun scheduleWhen(item: CalendarItem, zone: ZoneId = ZoneId.systemDefault()): String {
    val start = OffsetDateTime.parse(item.start).atZoneSameInstant(zone)
    val end = OffsetDateTime.parse(item.end).atZoneSameInstant(zone)
    val day = DateTimeFormatter.ofPattern("EEE d MMM")
    if (item.allDay) {
        val last = end.minusDays(1)
        return if (!last.toLocalDate().isAfter(start.toLocalDate())) day.format(start) else "${day.format(start)} to ${day.format(last)}"
    }
    val time = DateTimeFormatter.ofPattern("HH:mm")
    return if (end.isAfter(start)) "${day.format(start)}, ${time.format(start)}–${time.format(end)}" else "${day.format(start)}, ${time.format(start)}"
}

/** Whether the line is shown at all: cancelled and declined events are not part of the owner's schedule. */
fun onSchedule(item: CalendarItem): Boolean = item.status != "cancelled" && item.response != "declined"

fun scheduleTitle(item: CalendarItem): String = if (item.titleMissing) "Untitled event" else item.title

/** A short reason in words, for the events that will not get a recording reminder. Null when one is on or the reason is not worth showing. */
fun reminderNote(item: CalendarItem): String? = when {
    item.remind -> "Reminder on"
    item.remindBlocked == "declined" -> "Declined"
    item.remindBlocked == "on_leave" -> "Skipped: you are on leave"
    item.remindBlocked == "unconfirmed_meeting" -> "Not confirmed as a meeting"
    else -> null
}
