package app.reachy.companion.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel
import app.reachy.companion.data.CLASS_LABEL
import app.reachy.companion.data.DocumentItem
import app.reachy.companion.data.STATE_LABEL

/** Chooses one of the library's documents for the chat. Only documents that are read can be chosen; the hub decides what the chat may then draw on. */
@Composable
fun DocumentPicker(model: AppViewModel, onChosen: (DocumentItem) -> Unit, onClose: () -> Unit) {
    val docs = model.docs
    LaunchedEffect(Unit) { docs.load() }
    var filter by remember { mutableStateOf("") }
    val shown = docs.documents.filter { filter.isBlank() || it.title.contains(filter.trim(), ignoreCase = true) }
    AlertDialog(
        onClose, title = { Text("Answer from a document") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Typed messages in this chat are then answered from the document you choose, with the pages named.", style = MaterialTheme.typography.bodySmall)
                if (docs.documents.size > 6) OutlinedTextField(filter, { filter = it }, label = { Text("Filter") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                when {
                    docs.enabled == false -> Text("The document library is turned off on the hub.")
                    docs.enabled == null && docs.error == null -> CircularProgressIndicator()
                    docs.error != null && docs.documents.isEmpty() -> Text(docs.error!!, color = MaterialTheme.colorScheme.error)
                    docs.documents.isEmpty() -> Text("There are no documents yet. Upload one in the Documents tab.")
                    else -> LazyColumn(Modifier.heightIn(max = 360.dp)) {
                        items(shown, key = { it.id }) { doc ->
                            Column(
                                Modifier.fillMaxWidth().let { if (doc.usable) it.clickable { onChosen(doc) } else it }.padding(vertical = 8.dp),
                            ) {
                                Text(doc.title, style = MaterialTheme.typography.bodyLarge, color = if (doc.usable) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.outline)
                                Text(
                                    listOfNotNull(CLASS_LABEL[doc.sensitivity] ?: doc.sensitivity, doc.projectScope, if (doc.usable) null else if (doc.state == "failed") "could not be read" else STATE_LABEL[doc.state] ?: "still being read").joinToString(" · "),
                                    style = MaterialTheme.typography.labelSmall,
                                )
                            }
                            HorizontalDivider()
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClose) { Text("Cancel") } },
    )
}
