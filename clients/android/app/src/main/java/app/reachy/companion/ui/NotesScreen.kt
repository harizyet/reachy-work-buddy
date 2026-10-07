package app.reachy.companion.ui

import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AlertDialog
import kotlinx.coroutines.delay
import androidx.compose.runtime.key
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.OffsetMapping
import androidx.compose.ui.text.input.TransformedText
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.reachy.companion.AppViewModel
import app.reachy.companion.data.Note
import app.reachy.companion.data.groupedNotes
import app.reachy.companion.data.joinNote
import app.reachy.companion.data.matchesNote
import app.reachy.companion.data.noteDate
import app.reachy.companion.data.notePreview
import app.reachy.companion.data.splitNote

private val Accent = androidx.compose.ui.graphics.Color(0xFFE0A800)

/** Notes in the Apple Notes style: a search box, month-grouped rounded lists, and an editor whose first line is the title. */
@Composable
fun NotesScreen(model: AppViewModel, modifier: Modifier = Modifier) {
    var openId by remember { mutableStateOf<String?>(null) }
    var composing by remember { mutableStateOf(false) }
    var query by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { model.loadNotes() }
    val open = model.notes.firstOrNull { it.id == openId }
    val editing = composing || open != null
    // Picking a note or starting a new one gives the editor a fresh start; a note being created keeps the same editor
    // when its id arrives, so typing is not interrupted.
    var editorKey by remember { mutableStateOf(0) }
    val created: (String) -> Unit = { id -> if (composing) { openId = id; composing = false } }
    val list: @Composable (Modifier) -> Unit = { m ->
        NoteList(
            model, query, { query = it }, selectedId = if (isWide()) openId else null,
            onOpen = { openId = it; composing = false; editorKey++ }, onCompose = { openId = null; composing = true; editorKey++ }, modifier = m,
        )
    }
    if (isWide()) {
        // Unfolded or landscape: the list stays on the left and the open note is edited on the right.
        TwoPane(modifier, listWidth = 380, list = { list(Modifier) }, detail = {
            if (editing) key(editorKey) { NoteEditor(model, open, onClose = { openId = null; composing = false }, Modifier, created) }
            else Text("Select a note, or tap the pencil to write one.", Modifier.padding(24.dp), color = MaterialTheme.colorScheme.outline)
        })
    } else if (editing) NoteEditor(model, open, onClose = { openId = null; composing = false }, modifier, created) else list(modifier)
}

@Composable
private fun NoteList(
    model: AppViewModel, query: String, onQuery: (String) -> Unit, selectedId: String?, onOpen: (String) -> Unit, onCompose: () -> Unit, modifier: Modifier,
) {
    val shown = model.notes.filter { matchesNote(it, query) }
    Box(modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            OutlinedTextField(
                query, onQuery, Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), singleLine = true,
                placeholder = { Text("Search") }, leadingIcon = { Icon(Icons.Default.Search, null) }, shape = RoundedCornerShape(12.dp),
            )
            ErrorLine(model.listError)
            if (model.notes.isEmpty()) Text("No notes yet. Tap the pencil to write one.", Modifier.padding(16.dp))
            LazyColumn(Modifier.weight(1f).padding(horizontal = 16.dp)) {
                groupedNotes(shown).forEach { (section, notes) ->
                    item(key = "h-$section") { Text(section, Modifier.padding(top = 16.dp, bottom = 6.dp, start = 4.dp), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold) }
                    item(key = "g-$section") {
                        Column(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f), RoundedCornerShape(14.dp))) {
                            notes.forEachIndexed { index, note ->
                                if (index > 0) HorizontalDivider(Modifier.padding(start = 16.dp))
                                NoteRow(note, selected = note.id == selectedId) { onOpen(note.id) }
                            }
                        }
                    }
                }
                item { Text(if (shown.size == 1) "1 Note" else "${shown.size} Notes", Modifier.fillMaxWidth().padding(vertical = 24.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline, textAlign = androidx.compose.ui.text.style.TextAlign.Center) }
            }
        }
        FloatingActionButton(onCompose, Modifier.align(Alignment.BottomEnd).padding(16.dp), containerColor = Accent) { Icon(Icons.Default.Edit, "New note") }
    }
}

@Composable
private fun NoteRow(note: Note, selected: Boolean = false, onOpen: () -> Unit) {
    Column(Modifier.fillMaxWidth().background(if (selected) Accent.copy(alpha = 0.3f) else androidx.compose.ui.graphics.Color.Transparent).clickable(onClick = onOpen).padding(horizontal = 16.dp, vertical = 10.dp)) {
        Text(note.title, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Row {
            Text(noteDate(note.updatedAt), style = MaterialTheme.typography.bodyMedium)
            Text("  " + notePreview(note), Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Default.Folder, null, Modifier.padding(end = 4.dp), tint = MaterialTheme.colorScheme.outline)
            Text("Notes", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
        }
    }
}

/** Makes the first line of the text large and bold, as the note's title. The text itself is unchanged. */
private object FirstLineTitle : VisualTransformation {
    override fun filter(text: AnnotatedString): TransformedText {
        val end = text.text.indexOf('\n').let { if (it < 0) text.length else it }
        val styled = buildAnnotatedString {
            append(text)
            addStyle(SpanStyle(fontSize = 28.sp, fontWeight = FontWeight.Bold), 0, end)
        }
        return TransformedText(styled, OffsetMapping.Identity)
    }
}

@Composable
private fun NoteEditor(model: AppViewModel, note: Note?, onClose: () -> Unit, modifier: Modifier, onCreated: (String) -> Unit = {}) {
    val context = LocalContext.current
    val original = remember { note?.let { joinNote(it.title, it.body) }.orEmpty() }
    var text by remember { mutableStateOf(original) }
    var menu by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    val focus = remember { FocusRequester() }
    val current by rememberUpdatedState(text)
    // Notes save themselves when you leave them, as in Apple Notes; an empty new note is never created.
    // Leaving runs this from the back handler and again when the editor is disposed, so it remembers what it already saved.
    // A note created here gets its id back, so later saves update it rather than creating another (the editor stays open
    // beside the list on a wide window).
    val saved = remember { object { var text = original; var id = note?.id; var inFlight = false } }
    fun commit(leaving: Boolean = false) {
        val parts = splitNote(current) ?: return
        if (current == saved.text) return
        if (saved.inFlight && saved.id == null) return   // the first save is still on its way; the next trigger sends the rest
        saved.text = current
        saved.inFlight = true
        model.saveNote(saved.id, parts.first, parts.second) { id -> val first = saved.id == null; saved.id = id; saved.inFlight = false; if (first) onCreated(id) }
    }
    // The note being edited: the one opened, or the one this editor created and has since saved.
    fun target(): Note? = note ?: model.notes.firstOrNull { it.id == saved.id }
    BackHandler { commit(); onClose() }
    DisposableEffect(Unit) { onDispose { if (!confirmDelete) commit(leaving = true) } }
    // Notes save themselves a moment after typing stops, as in Apple Notes.
    LaunchedEffect(text) { delay(900); commit() }
    LaunchedEffect(Unit) { if (note == null) focus.requestFocus() }
    Column(modifier.fillMaxSize().imePadding()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            TextButton({ commit(); onClose() }) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, null, tint = Accent)
                Text(" Notes", color = Accent)
            }
            Box(Modifier.weight(1f))
            IconButton({
                val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)
                context.startActivity(Intent.createChooser(send, "Share note"))
            }, enabled = text.isNotBlank()) { Icon(Icons.Default.Share, "Share note", tint = Accent) }
            Box {
                IconButton({ menu = true }) { Icon(Icons.Default.MoreVert, "Note options", tint = Accent) }
                DropdownMenu(menu, { menu = false }) {
                    DropdownMenuItem({ Text("Delete") }, { menu = false; if (target() != null) confirmDelete = true else onClose() })
                }
            }
        }
        BasicTextField(
            text, { text = it }, Modifier.fillMaxSize().padding(horizontal = 20.dp, vertical = 8.dp).focusRequester(focus),
            textStyle = TextStyle(color = MaterialTheme.colorScheme.onSurface, fontSize = 17.sp, lineHeight = 24.sp),
            cursorBrush = SolidColor(Accent), visualTransformation = FirstLineTitle,
            decorationBox = { inner -> Box { if (text.isEmpty()) Text("Title", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.outline); inner() } },
        )
    }
    val doomed = if (confirmDelete) target() else null
    if (doomed != null) AlertDialog(
        onDismissRequest = { confirmDelete = false },
        title = { Text("Delete this note?") }, text = { Text("“${doomed.title}” will be deleted. This cannot be undone.") },
        confirmButton = { TextButton({ model.deleteNote(doomed); confirmDelete = false; onClose() }) { Text("Delete") } },
        dismissButton = { TextButton({ confirmDelete = false }) { Text("Cancel") } },
    )
}
