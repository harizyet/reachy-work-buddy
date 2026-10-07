package app.reachy.companion.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel

@Composable
fun TasksScreen(model: AppViewModel, modifier: Modifier = Modifier) {
    var draft by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { model.loadTasks() }
    Column(modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(draft, { draft = it }, Modifier.weight(1f), placeholder = { Text("Add a task") }, singleLine = true)
            IconButton({ model.addTask(draft); draft = "" }, enabled = draft.isNotBlank()) { Icon(Icons.Default.Add, "Add task") }
        }
        ErrorLine(model.listError)
        if (model.tasks.isEmpty()) Text("Nothing to do.", Modifier.padding(16.dp), style = MaterialTheme.typography.bodyMedium)
        LazyColumn {
            items(model.tasks, key = { it.id }) { task ->
                Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(task.done, { model.toggleTask(task) })
                    Text(
                        task.text, Modifier.weight(1f),
                        textDecoration = if (task.done) TextDecoration.LineThrough else null,
                        color = if (task.done) MaterialTheme.colorScheme.outline else MaterialTheme.colorScheme.onSurface,
                    )
                    IconButton({ model.deleteTask(task) }) { Icon(Icons.Default.Delete, "Delete task") }
                }
            }
        }
    }
}

@Composable
fun ErrorLine(message: String?) {
    if (message != null) Text(message, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 16.dp))
}
