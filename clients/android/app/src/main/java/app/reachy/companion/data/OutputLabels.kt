package app.reachy.companion.data

/** Which model wrote a summary or minutes, in the owner's words. An unknown tier is shown as it came rather than hidden. */
fun tierLabel(tier: String): String = when (tier) {
    "local" -> "the local model"
    "deep" -> "the larger local model"
    "cloud" -> "the cloud model"
    else -> tier
}

/** The line above the text of a finished summary or minutes. */
fun writtenByLine(tier: String, generatedAt: String): String =
    "Written by ${tierLabel(tier)}" + if (generatedAt.length >= 16) " · ${generatedAt.take(16).replace('T', ' ')}" else ""

/** The line shown while one is being written, on the tier the owner picked. */
fun writingLine(name: String, model: String): String = "Writing the $name on ${tierLabel(model)}…"
