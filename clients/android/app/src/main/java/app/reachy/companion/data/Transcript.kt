package app.reachy.companion.data

/** The diarization speaker with the most time overlapping this transcript segment. */
fun speakerFor(meeting: Meeting, segment: Segment): String? {
    val spans = meeting.speakers.orEmpty().filter { it.speaker != null }
    val overlapping = spans.map { it to (minOf(it.end, segment.end) - maxOf(it.start, segment.start)) }.filter { it.second > 0 }
    // A zero-length transcript segment falls back to whoever is speaking at its start.
    return overlapping.maxByOrNull { it.second }?.first?.speaker
        ?: spans.firstOrNull { segment.start >= it.start && segment.start < it.end }?.speaker
}

/** The speaker of transcript segment [index]: the server's stored alignment, or (for a meeting not yet aligned) the overlap. */
fun speakerAt(meeting: Meeting, index: Int, segment: Segment): String? {
    val stored = meeting.aligned
    return if (stored != null && stored.size == meeting.transcript.orEmpty().size) stored[index].speaker else speakerFor(meeting, segment)
}

/** The owner's name for a speaker, else "Speaker N" for SPEAKER_NN labels, else the raw label. */
fun speakerDisplayName(meeting: Meeting, label: String): String {
    meeting.speakerNames[label]?.takeIf { it.isNotBlank() }?.let { return it }
    val number = Regex("^SPEAKER_(\\d+)$").matchEntire(label)?.groupValues?.get(1)?.toIntOrNull()
    return if (number != null) "Speaker ${number + 1}" else label
}

/** Corrected text for a segment when the owner accepted one, else the raw transcript text. */
fun segmentText(meeting: Meeting, index: Int): String =
    meeting.corrections[index.toString()] ?: meeting.transcript.orEmpty().getOrNull(index)?.text?.trim().orEmpty()

fun speakerLabels(meeting: Meeting): List<String> = meeting.speakers.orEmpty().mapNotNull { it.speaker }.distinct().sorted()

/** Mirrors the server's matching: case-insensitive, whole-word where the text starts/ends with a word character. */
fun replacementRegex(find: String): Regex {
    val start = if (find.firstOrNull()?.let { it.isLetterOrDigit() || it == '_' } == true) "\\b" else ""
    val end = if (find.lastOrNull()?.let { it.isLetterOrDigit() || it == '_' } == true) "\\b" else ""
    return Regex(start + Regex.escape(find) + end, RegexOption.IGNORE_CASE)
}

/** How many segments (using their current, possibly corrected, text) contain [find]. */
fun countOccurrences(meeting: Meeting, find: String): Int {
    if (find.isBlank()) return 0
    val regex = replacementRegex(find)
    return meeting.transcript.orEmpty().indices.count { regex.containsMatchIn(segmentText(meeting, it)) }
}

/** The transcript line being spoken at [seconds], or null between lines. */
fun lineAt(segments: List<Segment>, seconds: Double): Int? =
    segments.indexOfFirst { seconds >= it.start && seconds < it.end }.takeIf { it >= 0 }

/** Seconds of the recording the phone captured no audio for; 0 when none or not yet checked. */
fun silentSeconds(meeting: Meeting): Double = meeting.audioGaps?.seconds ?: 0.0

fun gapNotice(meeting: Meeting): String =
    "${clockText(silentSeconds(meeting))} of this recording has no audio — the phone stopped capturing sound (for example when it locked or another app used the microphone). Lines marked with a warning may be missing or unreliable."

fun lineIsSilent(meeting: Meeting, index: Int): Boolean = meeting.audioGaps?.segments?.contains(index) == true

private fun clockText(seconds: Double): String = "%d:%02d".format(seconds.toInt() / 60, seconds.toInt() % 60)
