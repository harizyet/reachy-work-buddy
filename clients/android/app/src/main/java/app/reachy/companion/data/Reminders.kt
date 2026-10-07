package app.reachy.companion.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.time.temporal.ChronoUnit
import java.util.Locale

/** A timed reminder. The hub can complete one but not reopen it. */
@Serializable
data class Reminder(
    val id: String,
    val text: String,
    @SerialName("due_at") val dueAt: String,
    val status: String = "pending",
) {
    val done get() = status == "done"
}

/** "Today, 4:00 PM", "Tomorrow, 9:00 AM", "Yesterday, 9:30 AM", otherwise a short date and the time. */
fun reminderWhen(dueAt: String, now: OffsetDateTime = OffsetDateTime.now(), zone: ZoneId = ZoneId.systemDefault(), locale: Locale = Locale.getDefault()): String {
    val due = OffsetDateTime.parse(dueAt).atZoneSameInstant(zone)
    val days = ChronoUnit.DAYS.between(now.atZoneSameInstant(zone).toLocalDate(), due.toLocalDate())
    val day = when (days) {
        0L -> "Today"
        1L -> "Tomorrow"
        -1L -> "Yesterday"
        else -> due.format(DateTimeFormatter.ofLocalizedDate(FormatStyle.SHORT).withLocale(locale))
    }
    return "$day, " + due.format(DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT).withLocale(locale))
}

fun isOverdue(reminder: Reminder, now: OffsetDateTime = OffsetDateTime.now()): Boolean =
    !reminder.done && !OffsetDateTime.parse(reminder.dueAt).isAfter(now)

/** Pending reminders soonest first; completed ones most recent first. */
fun pendingReminders(all: List<Reminder>): List<Reminder> = all.filter { !it.done }.sortedBy { OffsetDateTime.parse(it.dueAt) }
fun completedReminders(all: List<Reminder>): List<Reminder> = all.filter { it.done }.sortedByDescending { OffsetDateTime.parse(it.dueAt) }
