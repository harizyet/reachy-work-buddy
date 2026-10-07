package app.reachy.companion.data

import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.time.temporal.ChronoUnit
import java.util.Locale

private const val TITLE_MAX = 200

/** A note is edited as one block of text whose first line is its title, like Apple Notes. */
fun joinNote(title: String, body: String): String = if (body.isEmpty()) title else "$title\n$body"

/** Splits edited text into the stored title and body; null when there is nothing to save. */
fun splitNote(text: String): Pair<String, String>? {
    val trimmed = text.trimStart()
    if (trimmed.isBlank()) return null
    val firstLine = trimmed.substringBefore('\n').trimEnd()
    val rest = if ('\n' in trimmed) trimmed.substringAfter('\n').trimStart('\n') else ""
    val title = firstLine.take(TITLE_MAX)
    val overflow = firstLine.drop(TITLE_MAX)
    val body = when {
        overflow.isEmpty() -> rest
        rest.isEmpty() -> overflow
        else -> "$overflow\n$rest"
    }
    return title to body.trimEnd()
}

private fun day(iso: String, zone: ZoneId): LocalDate = OffsetDateTime.parse(iso).atZoneSameInstant(zone).toLocalDate()

/** The list heading a note sits under: Today, Yesterday, Previous 7 Days, Previous 30 Days, then its month. */
fun noteSection(updatedAt: String, now: OffsetDateTime = OffsetDateTime.now(), zone: ZoneId = ZoneId.systemDefault(), locale: Locale = Locale.getDefault()): String {
    val today = now.atZoneSameInstant(zone).toLocalDate()
    val date = day(updatedAt, zone)
    val days = ChronoUnit.DAYS.between(date, today)
    return when {
        days <= 0 -> "Today"
        days == 1L -> "Yesterday"
        days <= 7 -> "Previous 7 Days"
        days <= 30 -> "Previous 30 Days"
        date.year == today.year -> date.month.getDisplayName(java.time.format.TextStyle.FULL, locale)
        else -> "${date.month.getDisplayName(java.time.format.TextStyle.FULL, locale)} ${date.year}"
    }
}

/** The date shown on a row: the time today, "Yesterday", the weekday this week, else a short date. */
fun noteDate(updatedAt: String, now: OffsetDateTime = OffsetDateTime.now(), zone: ZoneId = ZoneId.systemDefault(), locale: Locale = Locale.getDefault()): String {
    val local = OffsetDateTime.parse(updatedAt).atZoneSameInstant(zone)
    val days = ChronoUnit.DAYS.between(local.toLocalDate(), now.atZoneSameInstant(zone).toLocalDate())
    return when {
        days <= 0 -> local.format(DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT).withLocale(locale))
        days == 1L -> "Yesterday"
        days <= 7 -> local.dayOfWeek.getDisplayName(java.time.format.TextStyle.FULL, locale)
        else -> local.format(DateTimeFormatter.ofLocalizedDate(FormatStyle.SHORT).withLocale(locale))
    }
}

fun notePreview(note: Note): String = note.body.lineSequence().map { it.trim() }.firstOrNull { it.isNotEmpty() } ?: "No additional text"

/** Notes newest first, in the order of their headings. */
fun groupedNotes(notes: List<Note>, now: OffsetDateTime = OffsetDateTime.now(), zone: ZoneId = ZoneId.systemDefault()): List<Pair<String, List<Note>>> =
    notes.filter { it.updatedAt.isNotEmpty() }.sortedByDescending { OffsetDateTime.parse(it.updatedAt) }
        .groupBy { noteSection(it.updatedAt, now, zone) }.toList() +
        notes.filter { it.updatedAt.isEmpty() }.let { if (it.isEmpty()) emptyList() else listOf("Notes" to it) }

fun matchesNote(note: Note, query: String): Boolean =
    query.isBlank() || note.title.contains(query.trim(), ignoreCase = true) || note.body.contains(query.trim(), ignoreCase = true)
