package app.reachy.companion.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * The owner's document library as the hub serves it (Phase 50). The server decides everything: which documents exist, their class,
 * whether they can be read and what an answer may draw on. Nothing here is a privacy ceiling or an ownership claim.
 */
@Serializable
data class DocumentItem(
    val id: String,
    val title: String,
    val filename: String = "",
    @SerialName("size_bytes") val sizeBytes: Long = 0,
    val sensitivity: String = "work-private",
    @SerialName("project_scope") val projectScope: String? = null,
    val state: String = "uploaded",
    val tier: String? = null,
    @SerialName("page_count") val pageCount: Int? = null,
    @SerialName("error_code") val errorCode: String? = null,
    @SerialName("next_tier") val nextTier: String? = null,
) {
    /** Answers, search and the inspector work on a document that is read (or read as far as it is so far). */
    val usable get() = state == "ready" || state == "partial"
    /** Still being read, so the list refreshes itself. */
    val waiting get() = state == "uploaded" || state == "queued" || state == "processing" || state == "partial"
}

@Serializable
data class DocumentSection(val pages: String = "", val summary: String = "")

@Serializable
data class DocumentSummary(
    val id: String,
    val style: String = "ordinary",
    val status: String = "running",
    val text: String = "",
    val sections: List<DocumentSection> = emptyList(),
    @SerialName("pages_covered") val pagesCovered: String? = null,
    val truncated: Boolean = false,
    val tier: String? = null,
    val stale: Boolean = false,
    @SerialName("error_code") val errorCode: String? = null,
)

@Serializable
data class DocumentHit(val snippet: String = "", val page: Int? = null)

@Serializable
data class DocumentSearch(val hits: List<DocumentHit> = emptyList(), val complete: Boolean = true)

/** A page the reply drew on; the hub records it from the excerpts it supplied, never from the model's wording. */
@Serializable
data class Citation(@SerialName("document_id") val documentId: String, val title: String = "", val page: Int)

@Serializable
data class ChatDocument(val id: String, val title: String = "", val available: Boolean = true)

@Serializable
data class InspectBlock(val block: Int, val type: String = "", val bbox: List<Double>? = null)

@Serializable
data class InspectPage(
    val page: Int,
    @SerialName("page_count") val pageCount: Int = 1,
    val tier: String = "",
    @SerialName("page_image") val pageImage: Boolean = false,
    @SerialName("width_pt") val widthPt: Double? = null,
    @SerialName("height_pt") val heightPt: Double? = null,
    val blocks: List<InspectBlock> = emptyList(),
    val markdown: String = "",
)

val TIER_LABEL = mapOf("flash" to "Flash", "basic" to "Basic", "standard" to "Standard", "advanced" to "Advanced")
val CLASS_LABEL = mapOf("public" to "Public", "work-private" to "Work private", "sensitive" to "Sensitive")
val STATE_LABEL = mapOf(
    "uploaded" to "Waiting", "queued" to "Queued", "processing" to "Reading", "ready" to "Ready",
    "partial" to "Partly read", "failed" to "Could not be read", "deleting" to "Deleting",
)

fun sizeLabel(bytes: Long): String = if (bytes >= 1_048_576) "%.1f MB".format(bytes / 1_048_576.0) else "${maxOf(1L, Math.round(bytes / 1024.0))} KB"

/** The upload types the library accepts. The hub checks the content as well; this only keeps an unsupported pick from being sent. */
fun uploadContentType(name: String, reported: String?): String? {
    val ext = name.substringAfterLast('.', "").lowercase()
    return when (ext) {
        "pdf" -> "application/pdf"
        "docx" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        "png" -> "image/png"
        "jpg", "jpeg" -> "image/jpeg"
        else -> when (reported) {
            "application/pdf", "image/png", "image/jpeg", "application/vnd.openxmlformats-officedocument.wordprocessingml.document" -> reported
            else -> null
        }
    }
}

val UPLOAD_MIME_TYPES = arrayOf(
    "application/pdf", "image/png", "image/jpeg", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)

/** A title for an upload that was not given one: the file name without its extension. */
fun titleFromFilename(name: String): String = name.substringBeforeLast('.', name).trim().ifEmpty { name }.take(200)

/** Pages for the "From pages 2, 4 of “Title”" note under an answer: each page once, in order. */
fun citedPages(citations: List<Citation>): List<Int> = citations.map { it.page }.distinct().sorted()

fun pagesLabel(pages: List<Int>): String = if (pages.size == 1) "page ${pages[0]}" else "pages ${pages.joinToString(", ")}"

/** The block under a tap on the page picture (fractions of the page), the smallest one when blocks overlap. */
fun blockAt(blocks: List<InspectBlock>, x: Double, y: Double): InspectBlock? =
    blocks.filter { b -> b.bbox?.let { it.size == 4 && x >= it[0] && x <= it[2] && y >= it[1] && y <= it[3] } == true }
        .minByOrNull { b -> b.bbox!!.let { (it[2] - it[0]) * (it[3] - it[1]) } }

fun describeBlock(block: InspectBlock): String {
    val box = block.bbox?.takeIf { it.size == 4 } ?: return "No position"
    fun pct(v: Double) = "${Math.round(v * 100)}%"
    return "From ${pct(box[0])} across and ${pct(box[1])} down; ${pct(box[2] - box[0])} wide, ${pct(box[3] - box[1])} tall"
}

/** What an extracted page is shown as. Always plain text: MinerU's HTML is never rendered in the app, and the markdown is never interpreted as markup beyond these shapes. */
sealed interface Part {
    data class Heading(val level: Int, val text: String) : Part
    data class Paragraph(val text: String) : Part
    data class Table(val rows: List<List<String>>) : Part
}

private val TABLE_ROW = Regex("<tr[^>]*>(.*?)</tr>", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))
private val TABLE_CELL = Regex("<t[dh][^>]*>(.*?)</t[dh]>", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))
private val TAG = Regex("<[^>]*>")

private fun plain(html: String): String = html.replace(TAG, " ").replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    .replace("&quot;", "\"").replace("&#39;", "'").replace("&amp;", "&").replace(Regex("\\s+"), " ").trim()

private fun pipeCells(line: String): List<String> = line.trim().trim('|').split('|').map { it.trim() }
private fun isDivider(line: String) = line.trim().trim('|').split('|').all { cell -> cell.trim().matches(Regex(":?-{1,}:?")) } && line.contains('-')

/** Parses MinerU's page markdown into headings, paragraphs and tables (pipe tables and the HTML tables MinerU also writes). */
fun parseExtracted(markdown: String): List<Part> {
    val parts = mutableListOf<Part>()
    val paragraph = StringBuilder()
    fun flush() { if (paragraph.isNotBlank()) parts += Part.Paragraph(plain(paragraph.toString())); paragraph.clear() }
    val lines = markdown.lines()
    var i = 0
    while (i < lines.size) {
        val line = lines[i]
        val trimmed = line.trim()
        when {
            trimmed.isEmpty() -> { flush(); i++ }
            trimmed.startsWith("<table", ignoreCase = true) -> {
                flush()
                val html = StringBuilder()
                while (i < lines.size) { html.append(lines[i]).append('\n'); val done = lines[i].contains("</table>", ignoreCase = true); i++; if (done) break }
                val rows = TABLE_ROW.findAll(html).map { row -> TABLE_CELL.findAll(row.groupValues[1]).map { plain(it.groupValues[1]) }.toList() }.filter { it.isNotEmpty() }.toList()
                if (rows.isNotEmpty()) parts += Part.Table(rows)
            }
            trimmed.startsWith("|") && i + 1 < lines.size && isDivider(lines[i + 1]) -> {
                flush()
                val rows = mutableListOf(pipeCells(trimmed))
                i += 2
                while (i < lines.size && lines[i].trim().startsWith("|")) { rows += pipeCells(lines[i]); i++ }
                parts += Part.Table(rows)
            }
            trimmed.startsWith("#") -> {
                flush()
                val level = trimmed.takeWhile { it == '#' }.length
                if (level in 1..6 && trimmed.getOrNull(level) == ' ') parts += Part.Heading(level, plain(trimmed.drop(level + 1)))
                else parts += Part.Paragraph(plain(trimmed))
                i++
            }
            else -> { if (paragraph.isNotEmpty()) paragraph.append(' '); paragraph.append(trimmed); i++ }
        }
    }
    flush()
    return parts
}
