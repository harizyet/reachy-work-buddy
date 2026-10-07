package app.reachy.companion.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel
import app.reachy.companion.data.Note
import androidx.compose.foundation.layout.Box

@Composable
fun NotesScreen(model: AppViewModel, modifier: Modifier = Modifier) {
    var editing by remember { mutableStateOf<Note?>(null) }
    var creating by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { model.loadNotes() }
    Box(modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            ErrorLine(model.listError)
            if (model.notes.isEmpty()) Text("No notes yet. Tap + to write one.", Modifier.padding(16.dp))
            LazyColumn {
                items(model.notes, key = { it.id }) { note ->
                    Column(Modifier.fillMaxWidth().clickable { editing = note }.padding(16.dp)) {
                        Text(note.title, style = MaterialTheme.typography.titleMedium)
                        if (note.body.isNotBlank()) Text(note.body, maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                    }
                    HorizontalDivider()
                }
            }
        }
        FloatingActionButton({ creating = true }, Modifier.align(Alignment.BottomEnd).padding(16.dp)) { Icon(Icons.Default.Add, "New note") }
    }
    if (creating || editing != null) {
        NoteDialog(
            editing, onDismiss = { creating = false; editing = null },
            onSave = { title, body -> model.saveNote(editing?.id, title, body); creating = false; editing = null },
            onDelete = editing?.let { note -> { model.deleteNote(note); editing = null } },
        )
    }
}

@Composable
private fun NoteDialog(note: Note?, onDismiss: () -> Unit, onSave: (String, String) -> Unit, onDelete: (() -> Unit)?) {
    var title by remember { mutableStateOf(note?.title.orEmpty()) }
    var body by remember { mutableStateOf(note?.body.orEmpty()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (note == null) "New note" else "Edit note") },
        text = {
            Column {
                OutlinedTextField(title, { title = it }, label = { Text("Title") }, singleLine = true)
                OutlinedTextField(body, { body = it }, label = { Text("Note") }, minLines = 4, modifier = Modifier.padding(top = 8.dp))
            }
        },
        confirmButton = { TextButton({ onSave(title, body) }, enabled = title.isNotBlank()) { Text("Save") } },
        dismissButton = {
            Row {
                if (onDelete != null) TextButton(onDelete) { Text("Delete") }
                TextButton(onDismiss) { Text("Cancel") }
            }
        },
    )
}
