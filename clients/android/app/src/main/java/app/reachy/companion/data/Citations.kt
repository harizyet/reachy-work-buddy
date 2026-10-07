package app.reachy.companion.data

import java.net.URI

/** Only plain http(s) links without embedded credentials are ever made tappable; anything else stays literal text. */
fun safeUrl(value: String): String? = try {
    val uri = URI(value.trim())
    if ((uri.scheme == "http" || uri.scheme == "https") && uri.userInfo == null && !uri.host.isNullOrBlank()) uri.toString() else null
} catch (e: Exception) { null }

/** One piece of an answer: plain text, or a citation marker like [S1] with its link when the source has a safe URL. */
sealed interface Piece {
    data class Text(val text: String) : Piece
    data class Cite(val label: String, val url: String?) : Piece
}

private val CITATION = Regex("\\[S(\\d+)]")

/** Splits an answer on the model's [S1], [S2] markers. An unknown id (or an unsafe URL) is left as plain, unlinked text. */
fun citedPieces(text: String, sources: List<WebSource>): List<Piece> {
    if (sources.isEmpty()) return listOf(Piece.Text(text))
    val out = mutableListOf<Piece>()
    var last = 0
    for (match in CITATION.findAll(text)) {
        if (match.range.first > last) out += Piece.Text(text.substring(last, match.range.first))
        val url = sources.getOrNull(match.groupValues[1].toInt() - 1)?.url?.let(::safeUrl)
        out += if (url != null) Piece.Cite(match.value, url) else Piece.Text(match.value)
        last = match.range.last + 1
    }
    if (last < text.length) out += Piece.Text(text.substring(last))
    return out
}

/** "[S1] clickhouse.com: Title" for the visible Sources list. */
fun sourceLabel(index: Int, source: WebSource): String =
    "[S${index + 1}] " + (if (source.sourceDomain.isNotBlank()) "${source.sourceDomain}: " else "") + source.title.ifBlank { source.url }
