package app.reachy.companion.ui

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel
import app.reachy.companion.DocumentsModel
import app.reachy.companion.data.CLASS_LABEL
import app.reachy.companion.data.DocumentItem
import app.reachy.companion.data.STATE_LABEL
import app.reachy.companion.data.TIER_LABEL
import app.reachy.companion.data.UPLOAD_MIME_TYPES
import app.reachy.companion.data.citedPages
import app.reachy.companion.data.cleanSnippet
import app.reachy.companion.data.needsWriting
import app.reachy.companion.data.pagesLabel
import app.reachy.companion.data.shownSummaryStyle
import app.reachy.companion.data.sizeLabel
import app.reachy.companion.data.titleFromFilename
import app.reachy.companion.data.uploadContentType

/** The owner's document library on the phone: upload, status, and one document at a time with its questions, search, summaries and inspector. */
@Composable
fun DocumentsScreen(model: AppViewModel, modifier: Modifier = Modifier) {
    val docs = model.docs
    LaunchedEffect(Unit) { docs.load() }
    val wide = isWide()
    Box(modifier.fillMaxSize()) {
        when {
            docs.enabled == false -> Notice("The document library is turned off on the hub.")
            docs.enabled == null && docs.documents.isEmpty() -> {
                if (docs.error != null) Notice(docs.error!!) else Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            }
            wide -> TwoPane(Modifier.fillMaxSize(), 360, list = { DocumentList(docs) }, detail = {
                val open = docs.open
                if (open != null) DocumentDetail(docs, open, showBack = false) else Notice("Choose a document to ask about it, search it, summarise it or look at how it was read.")
            })
            docs.open != null -> DocumentDetail(docs, docs.open!!, showBack = true)
            else -> DocumentList(docs)
        }
    }
}

@Composable
private fun Notice(text: String) {
    Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) { Text(text, style = MaterialTheme.typography.bodyMedium) }
}

private data class Picked(val uri: Uri, val name: String, val size: Long, val type: String)

@Composable
private fun DocumentList(docs: DocumentsModel) {
    val context = LocalContext.current
    var picked by remember { mutableStateOf<Picked?>(null) }
    var unsupported by remember { mutableStateOf<String?>(null) }
    // Android's own document picker: the app is given just the file the owner chooses, no storage permission.
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        var name = uri.lastPathSegment ?: "document"
        var size = -1L
        context.contentResolver.query(uri, null, null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                c.getColumnIndex(OpenableColumns.DISPLAY_NAME).takeIf { it >= 0 }?.let { name = c.getString(it) ?: name }
                c.getColumnIndex(OpenableColumns.SIZE).takeIf { it >= 0 && !c.isNull(it) }?.let { size = c.getLong(it) }
            }
        }
        val type = uploadContentType(name, context.contentResolver.getType(uri))
        if (type == null) unsupported = name else picked = Picked(uri, name, size, type)
    }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button({ picker.launch(UPLOAD_MIME_TYPES) }, enabled = !docs.uploading) { Icon(Icons.Default.Add, null); Text("Upload", Modifier.padding(start = 6.dp)) }
            Text("PDF, Word (DOCX), PNG or JPEG", style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(1f))
            IconButton({ docs.refresh() }) { Icon(Icons.Default.Refresh, "Refresh") }
        }
        if (docs.uploading) LinearProgressIndicator(Modifier.fillMaxWidth().padding(horizontal = 12.dp))
        docs.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) }
        if (docs.documents.isEmpty()) Notice("No documents yet. Upload one to ask questions about it, search it or have it summarised.")
        LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(docs.documents, key = { it.id }) { DocumentRow(it, selected = it.id == docs.openId) { docs.openDocument(it.id) } }
        }
    }
    unsupported?.let {
        AlertDialog({ unsupported = null }, confirmButton = { TextButton({ unsupported = null }) { Text("OK") } },
            title = { Text("That file type is not supported") }, text = { Text("“$it” is not a PDF, DOCX, PNG or JPEG file.") })
    }
    picked?.let { file ->
        UploadDialog(file, onCancel = { picked = null }) { title, sensitivity, project ->
            picked = null
            docs.upload(file.name, file.type, file.size, { context.contentResolver.openInputStream(file.uri) }, title, sensitivity, project)
        }
    }
}

@Composable
private fun UploadDialog(file: Picked, onCancel: () -> Unit, onUpload: (String, String, String?) -> Unit) {
    var title by remember { mutableStateOf(titleFromFilename(file.name)) }
    var project by remember { mutableStateOf("") }
    var sensitivity by remember { mutableStateOf("work-private") }
    AlertDialog(
        onCancel,
        title = { Text("Upload document") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("${file.name}${if (file.size >= 0) " (${sizeLabel(file.size)})" else ""}", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(title, { title = it.take(200) }, label = { Text("Title") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(project, { project = it.take(100) }, label = { Text("Project (optional)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Text("Classification", style = MaterialTheme.typography.labelLarge)
                ClassChoice(sensitivity) { sensitivity = it }
            }
        },
        confirmButton = { TextButton({ onUpload(title, sensitivity, project.ifBlank { null }) }, enabled = title.isNotBlank()) { Text("Upload") } },
        dismissButton = { TextButton(onCancel) { Text("Cancel") } },
    )
}

@Composable
private fun ClassChoice(selected: String, onSelect: (String) -> Unit) {
    Column {
        for ((value, label) in CLASS_LABEL) Row(Modifier.fillMaxWidth().clickable { onSelect(value) }, verticalAlignment = Alignment.CenterVertically) {
            RadioButton(selected == value, { onSelect(value) }); Text(label)
        }
    }
}

@Composable
private fun DocumentRow(doc: DocumentItem, selected: Boolean, onClick: () -> Unit) {
    Card(
        Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = if (selected) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(doc.title, style = MaterialTheme.typography.titleMedium, maxLines = 2)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                StatusChip(doc)
                Text(
                    listOfNotNull(CLASS_LABEL[doc.sensitivity] ?: doc.sensitivity, doc.projectScope).joinToString(" · "),
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            if (doc.waiting) LinearProgressIndicator(Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun StatusChip(doc: DocumentItem) {
    val failed = doc.state == "failed"
    AssistChip(
        onClick = {}, label = { Text(STATE_LABEL[doc.state] ?: doc.state) },
        colors = androidx.compose.material3.AssistChipDefaults.assistChipColors(labelColor = if (failed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface),
    )
}

private enum class Dlg { Rename, Class, Project, Reread, Delete }
private enum class DocTab(val title: String) { Ask("Ask"), Search("Search"), Summaries("Summaries"), Inspect("Inspect") }

@Composable
private fun DocumentDetail(docs: DocumentsModel, doc: DocumentItem, showBack: Boolean) {
    var menu by remember { mutableStateOf(false) }
    var dialog by remember { mutableStateOf<Dlg?>(null) }
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var inspectAt by remember { mutableIntStateOf(1) }
    if (showBack) BackHandler { docs.closeDocument() }
    Column(Modifier.fillMaxSize().imePadding()) {
        Row(Modifier.fillMaxWidth().padding(start = 4.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            if (showBack) IconButton({ docs.closeDocument() }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back to documents") }
            Text(doc.title, style = MaterialTheme.typography.titleMedium, maxLines = 2, modifier = Modifier.weight(1f).padding(start = if (showBack) 0.dp else 12.dp))
            Box {
                IconButton({ menu = true }) { Icon(Icons.Default.MoreVert, "Document actions") }
                DropdownMenu(menu, { menu = false }) {
                    DropdownMenuItem({ Text("Rename") }, { menu = false; dialog = Dlg.Rename })
                    DropdownMenuItem({ Text("Classification") }, { menu = false; dialog = Dlg.Class })
                    DropdownMenuItem({ Text("Project") }, { menu = false; dialog = Dlg.Project })
                    if (doc.nextTier != null && doc.usable) DropdownMenuItem({ Text("Read more carefully (${TIER_LABEL[doc.nextTier] ?: doc.nextTier})") }, { menu = false; dialog = Dlg.Reread })
                    if (doc.state == "failed") DropdownMenuItem({ Text("Try reading again") }, { menu = false; dialog = Dlg.Reread })
                    DropdownMenuItem({ Text("Delete") }, { menu = false; dialog = Dlg.Delete })
                }
            }
        }
        Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                StatusChip(doc)
                Text(CLASS_LABEL[doc.sensitivity] ?: doc.sensitivity, style = MaterialTheme.typography.labelMedium)
            }
            Text(
                listOfNotNull(
                    "${doc.filename} (${sizeLabel(doc.sizeBytes)})", doc.projectScope?.let { "Project: $it" },
                    doc.tier?.let { "Read at: ${TIER_LABEL[it] ?: it}" + (doc.pageCount?.let { n -> " · $n page${if (n == 1) "" else "s"}" } ?: "") },
                ).joinToString("\n"),
                style = MaterialTheme.typography.bodySmall,
            )
            if (doc.state == "failed") Text("This document could not be read (${doc.errorCode ?: "unknown reason"}).", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            if (doc.waiting) LinearProgressIndicator(Modifier.fillMaxWidth().padding(top = 4.dp))
        }
        docs.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) }
        TabRow(tab) { for ((i, t) in DocTab.entries.withIndex()) Tab(tab == i, { tab = i }, text = { Text(t.title) }) }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (!doc.usable) Notice(if (doc.state == "failed") "Nothing can be asked until the document is read." else "The document is still being read. This updates by itself.")
            else when (DocTab.entries[tab]) {
                DocTab.Ask -> AskTab(docs)
                DocTab.Search -> SearchTab(docs) { page -> inspectAt = page; tab = DocTab.Inspect.ordinal }
                DocTab.Summaries -> SummariesTab(docs)
                DocTab.Inspect -> DocumentInspector(docs, doc, inspectAt)
            }
        }
    }
    when (dialog) {
        Dlg.Rename -> TextDialog("Rename", doc.title, "Title", { dialog = null }) { docs.rename(it); dialog = null }
        Dlg.Project -> TextDialog("Project", doc.projectScope.orEmpty(), "Project (empty to clear)", { dialog = null }, allowBlank = true) { docs.assignProject(it); dialog = null }
        Dlg.Class -> {
            var choice by remember(doc.id) { mutableStateOf(doc.sensitivity) }
            AlertDialog(
                { dialog = null }, title = { Text("Classification") },
                text = {
                    Column {
                        ClassChoice(choice) { choice = it }
                        Text("Decides where answers from this document can be shown. Sensitive documents are never sent to a cloud model.", style = MaterialTheme.typography.bodySmall)
                    }
                },
                confirmButton = { TextButton({ docs.classify(choice); dialog = null }) { Text("Save") } },
                dismissButton = { TextButton({ dialog = null }) { Text("Cancel") } },
            )
        }
        Dlg.Reread -> AlertDialog(
            { dialog = null }, title = { Text(if (doc.state == "failed") "Try reading again?" else "Read more carefully?") },
            text = {
                Text(
                    if (doc.state == "failed") "The stored original is read again."
                    else "The stored original is read again at the ${TIER_LABEL[doc.nextTier] ?: doc.nextTier} level. It takes longer, and summaries made earlier are marked as out of date.",
                )
            },
            confirmButton = { TextButton({ docs.reprocess(if (doc.state == "failed") doc.tier else doc.nextTier); dialog = null }) { Text("Read again") } },
            dismissButton = { TextButton({ dialog = null }) { Text("Cancel") } },
        )
        Dlg.Delete -> AlertDialog(
            { dialog = null }, title = { Text("Delete this document?") },
            text = { Text("“${doc.title}” and everything read from it are removed from Reachy. A chat that has it attached will say it is gone.") },
            confirmButton = { TextButton({ docs.delete(); dialog = null }) { Text("Delete", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ dialog = null }) { Text("Cancel") } },
        )
        null -> {}
    }
}

@Composable
private fun TextDialog(title: String, initial: String, label: String, onCancel: () -> Unit, allowBlank: Boolean = false, onSave: (String) -> Unit) {
    var value by remember { mutableStateOf(initial) }
    AlertDialog(
        onCancel, title = { Text(title) },
        text = { OutlinedTextField(value, { value = it.take(200) }, label = { Text(label) }, singleLine = true, modifier = Modifier.fillMaxWidth()) },
        confirmButton = { TextButton({ onSave(value) }, enabled = allowBlank || value.isNotBlank()) { Text("Save") } },
        dismissButton = { TextButton(onCancel) { Text("Cancel") } },
    )
}

@Composable
private fun AskTab(docs: DocumentsModel) {
    var draft by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize()) {
        if (docs.exchanges.isEmpty()) Text(
            "Ask about this document. Answers use only excerpts of it and name the pages they came from.",
            style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(16.dp),
        )
        LazyColumn(Modifier.weight(1f), contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(docs.exchanges.size) { i ->
                val x = docs.exchanges[i]
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(x.question, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                    SelectionContainer {
                        Text(x.answer ?: x.failed ?: "Reading the document…", color = if (x.failed != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface)
                    }
                    val pages = citedPages(x.citations)
                    if (pages.isNotEmpty()) Text("From ${pagesLabel(pages)}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.secondary)
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(draft, { draft = it }, Modifier.weight(1f), placeholder = { Text("Ask about this document") }, maxLines = 4)
            IconButton({ docs.ask(draft); draft = "" }, enabled = draft.isNotBlank() && !docs.asking) { Icon(Icons.AutoMirrored.Filled.Send, "Ask") }
        }
    }
}

@Composable
private fun SearchTab(docs: DocumentsModel, onOpenPage: (Int) -> Unit) {
    var query by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(query, { query = it.take(500) }, Modifier.weight(1f), placeholder = { Text("Search inside this document") }, singleLine = true)
            FilledTonalButton({ docs.search(query) }, enabled = query.isNotBlank() && !docs.searching, modifier = Modifier.padding(start = 8.dp)) { Text("Search") }
        }
        if (docs.searching) LinearProgressIndicator(Modifier.fillMaxWidth())
        docs.searchResult?.let { result ->
            if (result.hits.isEmpty()) Text("Nothing in this document matches that.")
            else LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(result.hits.size) { i ->
                    val hit = result.hits[i]
                    Card(Modifier.fillMaxWidth().let { m -> if (hit.page != null) m.clickable { onOpenPage(hit.page) } else m }) {
                        Column(Modifier.padding(12.dp)) {
                            Text(cleanSnippet(hit.snippet), style = MaterialTheme.typography.bodyMedium)
                            Text(
                                if (hit.page != null) "Page ${hit.page}. Tap to see it in the inspector." else "Page not known",
                                style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.secondary,
                            )
                        }
                    }
                }
                if (!result.complete) item { Text("Only the first matches are shown.", style = MaterialTheme.typography.labelSmall) }
            }
        }
    }
}

@Composable
private fun SummariesTab(docs: DocumentsModel) {
    // The buttons choose which summary is shown below; one is written only when its style has none yet (see shownSummaryStyle and needsWriting).
    var chosen by remember(docs.openId) { mutableStateOf<String?>(null) }
    val shown = shownSummaryStyle(chosen, docs.summaries)
    val labels = listOf("ordinary" to "Ordinary", "executive" to "Executive", "technical" to "Technical")
    LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("Summaries of this document", style = MaterialTheme.typography.titleSmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 6.dp)) {
                for ((style, label) in labels) {
                    val exists = !needsWriting(style, docs.summaries)
                    val running = docs.summaries.any { it.style == style && it.status == "running" }
                    val text = if (running) "$label…" else if (exists) label else "Write ${label.lowercase()}"
                    val onClick = { chosen = style; if (!exists) docs.summarize(style) }
                    val padding = androidx.compose.foundation.layout.PaddingValues(horizontal = 10.dp)
                    if (shown == style) FilledTonalButton(onClick, enabled = !running, contentPadding = padding) { Text(text) }
                    else OutlinedButton(onClick, enabled = !running, contentPadding = padding) { Text(text) }
                }
            }
            docs.summaryError?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            if (shown == null) Text("No summary yet. Choose a style to have Reachy write one.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
            Text("A summary is Reachy's reading of the extracted text, not the original; check the pages it names.", style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(top = 4.dp))
        }
        val visible = docs.summaries.filter { it.style == shown }
        items(visible.size) { i ->
            val s = visible[i]
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(s.style.replaceFirstChar { it.uppercase() } + (s.pagesCovered?.let { " · pages $it" } ?: ""), style = MaterialTheme.typography.labelLarge)
                    if (s.stale) Text("Out of date: the document was read again since.", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelSmall)
                    when (s.status) {
                        "running" -> { Text("Writing…"); LinearProgressIndicator(Modifier.fillMaxWidth()) }
                        "failed" -> Text("This summary could not be made (${s.errorCode ?: "unknown reason"}).", color = MaterialTheme.colorScheme.error)
                        else -> {
                            SelectionContainer { Text(s.text) }
                            for (section in s.sections) if (s.sections.size > 1) Text("Pages ${section.pages}: ${section.summary}", style = MaterialTheme.typography.bodySmall)
                            if (s.truncated) Text("Only part of a long document was summarised.", style = MaterialTheme.typography.labelSmall)
                        }
                    }
                    if (s.status != "running") TextButton({ docs.summarize(s.style, force = true) }) { Text("Write again") }
                }
            }
        }
        item { HorizontalDivider() }
    }
}
