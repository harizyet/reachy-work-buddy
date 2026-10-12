package app.reachy.companion

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import app.reachy.companion.data.Citation
import app.reachy.companion.data.DocumentItem
import app.reachy.companion.data.DocumentSearch
import app.reachy.companion.data.DocumentSummary
import app.reachy.companion.data.InspectPage
import app.reachy.companion.data.ReachyApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** One question and answer in the Ask tab of a document. Not saved anywhere on the phone. */
data class DocumentExchange(val question: String, val answer: String? = null, val citations: List<Citation> = emptyList(), val failed: String? = null)

/**
 * The Documents screen's state: the library list (kept fresh while anything is being read), and the one document that is open with its
 * questions, search, summaries and inspector. Every decision (what exists, who may read it, what an answer draws on) is the hub's.
 */
class DocumentsModel(
    private val api: () -> ReachyApi,
    private val userId: () -> String?,
    private val scope: CoroutineScope,
    private val fail: (Exception) -> String,
) {
    var enabled by mutableStateOf<Boolean?>(null); private set
    val documents = mutableStateListOf<DocumentItem>()
    var error by mutableStateOf<String?>(null)
    var uploading by mutableStateOf(false); private set
    var loading by mutableStateOf(false); private set
    private var poll: Job? = null

    fun load() {
        scope.launch {
            loading = true
            try {
                enabled = api().documentLibraryEnabled()
                if (enabled == true) refreshNow()
                error = null
            } catch (e: Exception) { error = fail(e) } finally { loading = false }
        }
    }

    private suspend fun refreshNow() {
        val items = api().documents()
        documents.clear(); documents.addAll(items)
        // A document the owner had open may have been deleted elsewhere (the web Documents page, another device).
        if (openId != null && items.none { it.id == openId }) closeDocument()
        if (items.any { it.waiting } && poll?.isActive != true) poll = scope.launch {
            try {
                while (documents.any { it.waiting }) { delay(POLL_MS); runCatching { refreshNow() } }
            } finally { poll = null }
        }
    }

    fun refresh() { scope.launch { try { refreshNow(); error = null } catch (e: Exception) { error = fail(e) } } }

    fun upload(name: String, contentType: String, length: Long, open: () -> java.io.InputStream?, title: String?, sensitivity: String, project: String?) {
        scope.launch {
            uploading = true
            try {
                val created = api().uploadDocument(name, contentType, length, open, title, sensitivity, project)
                refreshNow(); error = null
                openDocument(created.id)
            } catch (e: Exception) { error = fail(e) } finally { uploading = false }
        }
    }

    fun clear() {
        poll?.cancel(); documents.clear(); enabled = null; closeDocument(); error = null
    }

    // --- the open document ---------------------------------------------------------------------------------------------------------------

    var openId by mutableStateOf<String?>(null); private set
    val open get() = documents.firstOrNull { it.id == openId }
    val exchanges = mutableStateListOf<DocumentExchange>()
    var asking by mutableStateOf(false); private set
    var searchResult by mutableStateOf<DocumentSearch?>(null); private set
    var searching by mutableStateOf(false); private set
    val summaries = mutableStateListOf<DocumentSummary>()
    var summaryError by mutableStateOf<String?>(null); private set
    private var summaryPoll: Job? = null

    fun openDocument(id: String) {
        if (openId != id) {
            closeDocument(); openId = id
            loadSummaries()
        }
    }

    fun closeDocument() {
        openId = null; exchanges.clear(); searchResult = null; summaries.clear(); summaryError = null; summaryPoll?.cancel()
        inspectPage = null; pageImage = null; blockImage = null; inspectError = null
    }

    private fun act(block: suspend (String) -> Unit) {
        val id = openId ?: return
        scope.launch { try { block(id); error = null } catch (e: Exception) { error = fail(e) } }
    }

    fun rename(title: String) = act { id -> api().patchDocument(id, title = title); refreshNow() }
    fun classify(sensitivity: String) = act { id -> api().patchDocument(id, sensitivity = sensitivity); refreshNow() }
    fun assignProject(project: String) = act { id ->
        if (project.isBlank()) api().patchDocument(id, clearProject = true) else api().patchDocument(id, projectScope = project)
        refreshNow()
    }
    /** Reads the original again at the next level up (or the same one, for a document that failed). */
    fun reprocess(tier: String?) = act { id -> api().reprocessDocument(id, tier); refreshNow() }
    fun delete() {
        val id = openId ?: return
        scope.launch {
            try { api().deleteDocument(id); closeDocument(); refreshNow(); error = null } catch (e: Exception) { error = fail(e) }
        }
    }

    fun ask(text: String) {
        val id = openId ?: return
        val user = userId() ?: return
        val question = text.trim()
        if (question.isEmpty() || asking) return
        exchanges.add(DocumentExchange(question)); asking = true
        val index = exchanges.lastIndex
        scope.launch {
            try {
                val reply = api().askDocument(user, id, question)
                exchanges[index] = exchanges[index].copy(answer = reply.reply, citations = reply.citations)
            } catch (e: Exception) { exchanges[index] = exchanges[index].copy(failed = fail(e)) } finally { asking = false }
        }
    }

    fun search(query: String) {
        val q = query.trim()
        if (q.isEmpty() || searching) return
        searching = true
        act { id -> try { searchResult = api().searchDocument(id, q) } finally { searching = false } }
    }

    fun loadSummaries() = act { id ->
        summaries.clear(); summaries.addAll(api().summaries(id)); followSummaries(id)
    }

    fun summarize(style: String, force: Boolean = false) = act { id ->
        summaryError = null
        try { api().startSummary(id, style, force) } catch (e: Exception) { summaryError = fail(e); return@act }
        summaries.clear(); summaries.addAll(api().summaries(id)); followSummaries(id)
    }

    private fun followSummaries(id: String) {
        if (summaries.none { it.status == "running" } || summaryPoll?.isActive == true) return
        summaryPoll = scope.launch {
            while (openId == id && summaries.any { it.status == "running" }) {
                delay(POLL_MS)
                runCatching { api().summaries(id) }.onSuccess { if (openId == id) { summaries.clear(); summaries.addAll(it) } }
            }
        }
    }

    // --- inspector ---------------------------------------------------------------------------------------------------------------------------

    var inspectPage by mutableStateOf<InspectPage?>(null); private set
    var pageImage by mutableStateOf<ByteArray?>(null); private set
    var blockImage by mutableStateOf<Pair<Int, ByteArray>?>(null); private set
    var inspectError by mutableStateOf<String?>(null); private set
    var inspecting by mutableStateOf(false); private set
    private var inspectJob: Job? = null

    /** Loads one page as MinerU extracted it, and MinerU's picture of the original page when there is one. */
    fun inspect(page: Int) {
        val id = openId ?: return
        inspectJob?.cancel()
        inspectJob = scope.launch {
            inspecting = true; inspectError = null; blockImage = null
            try {
                val data = api().inspectPage(id, page)
                inspectPage = data
                pageImage = if (data.pageImage) runCatching { api().pageImage(id, page) }.getOrNull() else null
            } catch (e: Exception) { inspectError = fail(e) } finally { inspecting = false }
        }
    }

    fun showBlock(block: Int) {
        val id = openId ?: return
        val page = inspectPage?.page ?: return
        scope.launch {
            try { blockImage = block to api().pageImage(id, page, block); inspectError = null } catch (e: Exception) { inspectError = fail(e) }
        }
    }

    fun hideBlock() { blockImage = null }

    companion object { const val POLL_MS = 2500L }
}
