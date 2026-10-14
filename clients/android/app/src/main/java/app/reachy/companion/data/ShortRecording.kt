package app.reachy.companion.data

/*
 * A meeting stopped almost at once was probably a mistake (a stray tap, a voice command misheard). Under DISCARD_BELOW_SECONDS there is nothing useful to analyse, so the clip
 * is deleted without asking and never uploaded; under ASK_BELOW_SECONDS the owner is asked before it goes up.
 */
const val DISCARD_BELOW_SECONDS = 10L
const val ASK_BELOW_SECONDS = 30L

enum class ShortVerdict { Discard, Ask, Keep }

fun shortRecordingVerdict(seconds: Long): ShortVerdict = when {
    seconds < DISCARD_BELOW_SECONDS -> ShortVerdict.Discard
    seconds < ASK_BELOW_SECONDS -> ShortVerdict.Ask
    else -> ShortVerdict.Keep
}

fun shortRecordingQuestion(seconds: Long) = "It looks like the meeting recorded is only $seconds ${if (seconds == 1L) "second" else "seconds"} long. Was it a mistake?"

fun discardedShortRecordingMessage(seconds: Long) = "The recording was only $seconds ${if (seconds == 1L) "second" else "seconds"}, too short to be useful, so it was deleted and not uploaded."
