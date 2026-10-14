package app.reachy.companion.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/*
 * The Home dashboard (docs/phase-51.md). The hub proxies core's read-only snapshot (`GET /home`) for the owner session. Every section carries its own `status`, so one failing source never hides
 * the others, and the phone shows exactly what the server sent: it computes no count, no weather number and no date of its own. Everything the screen decides - how a time reads, what a state
 * says, where a tap goes, how one refreshed section is merged into the saved snapshot - is here, pure, so it is tested on the JVM.
 */

val homeJson = Json { ignoreUnknownKeys = true; coerceInputValues = true }

@Serializable data class HomeRef(val screen: String = "", val id: String? = null)

@Serializable
data class HomeEvent(
    val id: String = "",
    val title: String = "",
    val start: String = "",
    val end: String = "",
    @SerialName("all_day") val allDay: Boolean = false,
    val classification: String? = null,
    val location: String? = null,
    val status: String = "confirmed",
    val redacted: Boolean = false,
    val ref: HomeRef = HomeRef(),
)

@Serializable
data class HomeFeed(val configured: Boolean = false, val freshness: String = "", @SerialName("age_seconds") val ageSeconds: Long? = null, val error: String? = null)

@Serializable
data class HomeSchedule(
    val status: String = "unavailable",
    val generation: Long? = null,
    val feed: HomeFeed? = null,
    @SerialName("feed_configured") val feedConfigured: Boolean? = null,
    val events: List<HomeEvent> = emptyList(),
    @SerialName("all_day") val allDay: List<HomeEvent> = emptyList(),
    @SerialName("on_leave") val onLeave: Boolean = false,
    @SerialName("next_event") val nextEvent: HomeEvent? = null,
)

@Serializable
data class HomeOrigin(val kind: String = "", @SerialName("meeting_title") val meetingTitle: String? = null, @SerialName("note_title") val noteTitle: String? = null)

@Serializable data class HomeTask(val id: String = "", val text: String = "", val origin: HomeOrigin? = null, val ref: HomeRef = HomeRef())

@Serializable
data class HomeTasks(
    val status: String = "unavailable",
    val total: Int = 0,
    val shown: Int = 0,
    @SerialName("from_meetings") val fromMeetings: Int = 0,
    val items: List<HomeTask> = emptyList(),
)

@Serializable data class HomeReminder(val id: String = "", val text: String = "", @SerialName("due_at") val dueAt: String = "", val ref: HomeRef = HomeRef())

@Serializable
data class HomeReminders(
    val status: String = "unavailable",
    @SerialName("upcoming_days") val upcomingDays: Int = 7,
    val overdue: List<HomeReminder> = emptyList(),
    val today: List<HomeReminder> = emptyList(),
    val upcoming: List<HomeReminder> = emptyList(),
)

@Serializable data class HomeProposal(val id: String = "", val text: String = "", @SerialName("note_title") val noteTitle: String? = null, val ref: HomeRef = HomeRef())
@Serializable data class HomeAction(val id: String = "", val text: String = "", val assignee: String? = null, @SerialName("meeting_title") val meetingTitle: String? = null, val ref: HomeRef = HomeRef())
@Serializable data class HomeProposalQueue(val status: String = "off", val count: Int = 0, val items: List<HomeProposal> = emptyList())
@Serializable data class HomeActionQueue(val status: String = "off", val count: Int = 0, val items: List<HomeAction> = emptyList())

@Serializable
data class HomeReviews(
    val status: String = "unavailable",
    val total: Int = 0,
    @SerialName("note_proposals") val noteProposals: HomeProposalQueue? = null,
    @SerialName("meeting_actions") val meetingActions: HomeActionQueue? = null,
)

@Serializable data class HomeAttribution(val name: String = "", val url: String = "", val license: String = "")
@Serializable data class HomeUnits(val temperature: String = "°C", val precipitation: String = "mm", val probability: String = "%")

@Serializable
data class HomeNow(val temperature: Double? = null, @SerialName("feels_like") val feelsLike: Double? = null, val summary: String? = null)

@Serializable
data class HomeToday(
    val high: Double? = null,
    val low: Double? = null,
    @SerialName("precipitation_total") val precipitationTotal: Double? = null,
    @SerialName("precipitation_probability") val precipitationProbability: Double? = null,
    val summary: String? = null,
)

@Serializable
data class HomeWeather(
    val status: String = "unavailable",
    val error: String? = null,
    val location: String? = null,
    @SerialName("observed_at") val observedAt: String? = null,
    @SerialName("age_seconds") val ageSeconds: Long? = null,
    val attribution: HomeAttribution? = null,
    val units: HomeUnits? = null,
    val current: HomeNow? = null,
    val today: HomeToday? = null,
)

@Serializable data class HomeQuickAction(val id: String = "", val label: String = "", val ref: HomeRef = HomeRef())

@Serializable
data class HomeSnapshot(
    @SerialName("generated_at") val generatedAt: String = "",
    val date: String = "",
    val sources: Map<String, String> = emptyMap(),
    val partial: Boolean = false,
    val restricted: Boolean = false,
    @SerialName("quick_actions") val quickActions: List<HomeQuickAction> = emptyList(),
    val schedule: HomeSchedule? = null,
    val tasks: HomeTasks? = null,
    val reminders: HomeReminders? = null,
    val reviews: HomeReviews? = null,
    val weather: HomeWeather? = null,
)

@Serializable
data class HomeBriefLine(val category: String = "", val status: String = "info", val text: String = "", val ref: HomeRef? = null)

@Serializable
data class HomeBrief(
    val mode: String = "deterministic",
    val text: String = "",
    val lines: List<HomeBriefLine> = emptyList(),
    val narrative: String? = null,
    val model: String? = null,
    val fallback: String? = null,
    val partial: Boolean = false,
    val restricted: Boolean = false,
)

val HOME_SECTIONS = listOf("schedule", "tasks", "reminders", "reviews", "weather")

fun parseHome(text: String): HomeSnapshot = homeJson.decodeFromString(text)
fun parseBrief(text: String): HomeBrief = homeJson.decodeFromString(text)

/** Puts one refreshed section into an earlier snapshot without touching the others; `partial` is recomputed from the sources. */
fun mergeSection(old: HomeSnapshot, fresh: HomeSnapshot, name: String): HomeSnapshot {
    val sources = old.sources + (fresh.sources[name]?.let { mapOf(name to it) } ?: emptyMap())
    val merged = when (name) {
        "schedule" -> old.copy(schedule = fresh.schedule)
        "tasks" -> old.copy(tasks = fresh.tasks)
        "reminders" -> old.copy(reminders = fresh.reminders)
        "reviews" -> old.copy(reviews = fresh.reviews)
        "weather" -> old.copy(weather = fresh.weather)
        else -> old
    }
    return merged.copy(sources = sources, partial = sources.values.any { it == "unavailable" || it == "partial" }, generatedAt = fresh.generatedAt)
}

// --- where a tap goes -----------------------------------------------------------------------------------------------------------------------------

/** The existing screen a reference opens. Tasks live on the Reminders screen (it lists the to-do list above the reminders); an unknown reference opens nothing. */
fun sectionFor(ref: HomeRef?): Section? = when (ref?.screen) {
    "calendar" -> Section.Calendar
    "tasks", "reminders" -> Section.Reminders
    "notes" -> Section.Notes
    "meetings" -> Section.Meetings
    "talk" -> Section.Talk
    else -> null
}

// --- how it reads -------------------------------------------------------------------------------------------------------------------------------

private fun at(iso: String, zone: ZoneId) = OffsetDateTime.parse(iso).atZoneSameInstant(zone)
fun clock(iso: String, zone: ZoneId = ZoneId.systemDefault(), locale: Locale = Locale.getDefault()): String =
    runCatching { at(iso, zone).format(DateTimeFormatter.ofLocalizedTime(java.time.format.FormatStyle.SHORT).withLocale(locale)) }.getOrDefault("")

fun dayClock(iso: String, zone: ZoneId = ZoneId.systemDefault(), locale: Locale = Locale.getDefault()): String =
    runCatching { at(iso, zone).format(DateTimeFormatter.ofPattern("EEE ", locale)) + clock(iso, zone, locale) }.getOrDefault("")

/** One event's time column: the class name for an all-day banner, otherwise the range. */
fun eventTime(e: HomeEvent, zone: ZoneId = ZoneId.systemDefault()): String =
    if (e.allDay) (CLASS_NAMES[e.classification] ?: "All day") else "${clock(e.start, zone)}–${clock(e.end, zone)}"

val CLASS_NAMES = mapOf("meeting" to "Meeting", "personal_appointment" to "Appointment", "leave_or_ooo" to "Leave", "all_day" to "All day", "unknown_timed" to "Timed event", "busy_private" to "Busy")

/** What a card says when its section has no content of its own. Null means the section has content (or its own wording) and should be drawn. */
fun stateLine(status: String?, offText: String = "This feature is turned off."): String? = when (status) {
    null -> "Not loaded yet."
    "restricted" -> "Not shown in this context."
    "unavailable" -> "This could not be read just now. Your other sections are not affected."
    "off" -> offText
    else -> null
}

fun weatherLines(w: HomeWeather): List<String> {
    val u = w.units ?: HomeUnits()
    val now = w.current ?: return emptyList()
    val today = w.today ?: return emptyList()
    fun d(v: Double?, unit: String, digits: Int = 0) = if (v == null) "—" else String.format(Locale.ROOT, "%.${digits}f", v) + unit
    val out = mutableListOf("${now.summary ?: "Conditions unavailable"} · ${d(now.temperature, u.temperature)}" + (now.feelsLike?.let { " (feels like ${d(it, u.temperature)})" } ?: ""))
    out += "Today ${d(today.low, u.temperature)} to ${d(today.high, u.temperature)}" + (today.summary?.let { " · $it" } ?: "")
    if (today.precipitationTotal != null) out += "Rain today: ${d(today.precipitationTotal, " " + u.precipitation, 1)}" + (today.precipitationProbability?.let { " · up to ${d(it, u.probability)} chance" } ?: "")
    return out
}

fun plural(n: Int, one: String, many: String = one + "s") = "$n ${if (n == 1) one else many}"

/** "Saved copy from 14:02" for the offline banner; the age is in words so a stale copy cannot pass for a live one. */
fun savedCopyLine(checkedMs: Long, nowMs: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val minutes = ((nowMs - checkedMs) / 60_000).coerceAtLeast(0)
    val age = when { minutes < 1 -> "just now"; minutes < 60 -> "$minutes min ago"; minutes < 24 * 60 -> "${minutes / 60} h ago"; else -> "${minutes / (24 * 60)} d ago" }
    return "Showing the copy saved on this phone from ${Instant.ofEpochMilli(checkedMs).atZone(zone).format(DateTimeFormatter.ofPattern("HH:mm"))} ($age)."
}

fun briefHeadline(b: HomeBrief): String = when {
    b.mode == "generated" && !b.narrative.isNullOrBlank() -> "Reworded by the local model" + (b.model?.let { " ($it)" } ?: "") + " from the lines below, which are the record."
    !b.fallback.isNullOrBlank() && b.fallback != "nothing_to_reword" -> "A written summary was not available, so this is the plain briefing."
    else -> "Plain briefing."
}

fun briefLabel(status: String): String = when (status) { "confirmed" -> "Confirmed"; "pending_review" -> "Suggestion"; else -> "Info" }
