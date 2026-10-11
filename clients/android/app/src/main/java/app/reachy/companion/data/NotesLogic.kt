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
    query.isBlank() || note.title.contains(query.trim(), ignoreCase = true) || note.body.contains(query.trim(), ignoreCase = true) ||
        (note.tag ?: "").contains(query.trim(), ignoreCase = true)

// ---- Folders. A note's tag is its folder under All Notes: slash-separated names, e.g. "Projects/Project StarWars/Finance".
// The rules repeat shared/models/note_tag.py (cases in services/companion-core/tests/test_note_tag.py); change both together.

const val NOTE_ROOT = "All Notes"
private const val TAG_MAX_DEPTH = 5
private const val TAG_MAX_NAME = 60

/** The canonical tag for what was typed, or null for none (blank, or just "All Notes"). Throws IllegalArgumentException (with a message to show) when too deep or a name is too long. */
fun normaliseNoteTag(raw: String): String? {
    var parts = raw.split('/').map { it.trim().split(Regex("\\s+")).filter(String::isNotEmpty).joinToString(" ") }.filter(String::isNotEmpty)
    if (parts.firstOrNull().equals(NOTE_ROOT, ignoreCase = true)) parts = parts.drop(1)
    if (parts.isEmpty()) return null
    require(parts.size <= TAG_MAX_DEPTH) { "A folder can have at most $TAG_MAX_DEPTH levels." }
    require(parts.all { it.length <= TAG_MAX_NAME }) { "Each folder name can have at most $TAG_MAX_NAME characters." }
    return parts.joinToString("/")
}

/** A folder in the tree implied by the notes' tags: [count] counts the notes in it and below it. */
data class NoteFolder(val path: String, val name: String, val depth: Int, val count: Int)

/** Every folder that holds a note, directly or below, in tree order (a folder, then what is in it). Names that differ only in case are one folder. */
fun noteFolders(notes: List<Note>): List<NoteFolder> {
    val found = linkedMapOf<String, Pair<List<String>, Int>>() // lower-cased path -> (display names, count)
    for (note in notes) {
        val names = note.tag?.split('/')?.filter(String::isNotEmpty) ?: continue
        for (depth in 1..names.size) {
            val key = names.take(depth).joinToString("/").lowercase()
            val (display, count) = found[key] ?: (names.take(depth) to 0)
            found[key] = display to count + 1
        }
    }
    return found.values.sortedWith(compareBy(String.CASE_INSENSITIVE_ORDER) { it.first.joinToString("\u0000") })
        .map { (names, count) -> NoteFolder(names.joinToString("/"), names.last(), names.size - 1, count) }
}

/** A null [folder] is All Notes (everything); a folder holds its own notes and those of the folders below it. */
fun inNoteFolder(note: Note, folder: String?): Boolean {
    if (folder == null) return true
    val tag = note.tag.orEmpty().lowercase()
    val want = folder.lowercase()
    return tag == want || tag.startsWith("$want/")
}

fun folderTrail(tag: String?): String = if (tag.isNullOrEmpty()) "Notes" else tag.split('/').joinToString(" \u203a ")
