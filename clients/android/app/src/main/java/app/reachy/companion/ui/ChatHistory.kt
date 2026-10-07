package app.reachy.companion.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel
import app.reachy.companion.data.ChatRecord
import app.reachy.companion.data.noteDate

/** Previous chats: pick one to read it, start a new one, or delete one. A side panel when unfolded, a drawer on a phone. */
@Composable
fun ChatHistoryPanel(model: AppViewModel, modifier: Modifier = Modifier, onPicked: () -> Unit = {}) {
    var deleting by remember { mutableStateOf<ChatRecord?>(null) }
    Column(modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 4.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Chats", Modifier.weight(1f), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            TextButton({ model.newChat(); onPicked() }) { Icon(Icons.Default.Add, null, Modifier.size(18.dp)); Text(" New chat") }
        }
        ErrorLine(model.listError)
        if (model.chatHistory.isEmpty()) Text("Your chats will appear here.", Modifier.padding(16.dp), color = MaterialTheme.colorScheme.outline)
        LazyColumn(Modifier.weight(1f)) {
            items(model.chatHistory, key = { it.id }) { record ->
                val selected = record.id == model.openChatId
                Row(
                    Modifier.fillMaxWidth().background(if (selected) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent)
                        .clickable { model.openChat(record.id); onPicked() }.padding(start = 16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f).padding(vertical = 10.dp)) {
                        Text(record.title, maxLines = 2, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.SemiBold)
                        if (record.updatedAt.isNotEmpty()) Text(noteDate(record.updatedAt), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
                    }
                    IconButton({ deleting = record }) { Icon(Icons.Default.Delete, "Delete chat: ${record.title}", tint = MaterialTheme.colorScheme.outline) }
                }
                HorizontalDivider()
            }
        }
    }
    deleting?.let { record ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text("Delete this chat?") },
            text = { Text("“${record.title}” and its saved messages will be removed from your chat history. This cannot be undone.") },
            confirmButton = { TextButton({ model.deleteChat(record); deleting = null }) { Text("Delete") } },
            dismissButton = { TextButton({ deleting = null }) { Text("Cancel") } },
        )
    }
}
