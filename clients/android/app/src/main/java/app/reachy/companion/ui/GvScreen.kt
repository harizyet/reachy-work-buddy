package app.reachy.companion.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import app.reachy.companion.AppViewModel
import app.reachy.companion.data.ENROLLMENT_PHRASES
import app.reachy.companion.data.GV_PLAN
import app.reachy.companion.data.cleanAlias
import app.reachy.companion.data.gvComplete
import app.reachy.companion.data.gvCounts

/**
 * The guided evaluation session (gate GV): labelled clips of the owner, a consenting second person, a replayed recording and synthetic speech go
 * to the hub's benchmark store, and `tools/voice_identity_benchmark.py` turns them into error rates on the owner's machine. The phone shows no
 * score and picks no threshold. Raw audio is kept on the hub until deleted here.
 */
@Composable
fun GvScreen(model: AppViewModel, onClose: () -> Unit) {
    val vi = model.voiceIdentity
    LaunchedEffect(Unit) { vi.refreshGv() }
    var selected by remember { mutableStateOf(GV_PLAN.first().id) }
    var password by remember { mutableStateOf("") }
    var consent by remember { mutableStateOf(false) }
    var alias by remember { mutableStateOf("person1") }
    val step = GV_PLAN.first { it.id == selected }
    val counts = gvCounts(vi.gv?.voiceSamples.orEmpty())
    val recorder = rememberClipRecorder(model) { wav ->
        if (!step.nonOwner || consent) vi.uploadGv(step, wav, alias)
    }
    val enabled = vi.gv?.benchmarkEnabled == true

    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize().padding(horizontal = 16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClose) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
                    Text("Voice evaluation", style = MaterialTheme.typography.titleLarge)
                }
                Text(
                    "This records labelled clips so the owner can measure false accepts and false rejects. The clips are raw audio kept (encrypted) on your homelab until you delete them here. " +
                        "Only record other people who have agreed, under an alias, never a name. The phone shows no scores and chooses no threshold.",
                    style = MaterialTheme.typography.bodySmall,
                )
                vi.message?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
                if (!enabled) {
                    OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth(), label = { Text("Your password") }, singleLine = true, visualTransformation = PasswordVisualTransformation())
                    Button({ vi.enableGv(password); password = "" }, enabled = !vi.busy && password.isNotBlank()) { Text("Switch on evaluation recording") }
                    Text("The hub also needs OWNER_RECOGNITION_CAPTURE_DIR set, or the clips vanish when it restarts.", style = MaterialTheme.typography.bodySmall)
                } else {
                    if (gvComplete(counts)) Text("Every block has its target number of clips. Run the evaluation tool on your computer.", style = MaterialTheme.typography.titleSmall)
                    HorizontalDivider()
                    for (item in GV_PLAN) {
                        val have = counts[item.condition] ?: 0
                        Row(Modifier.fillMaxWidth().selectable(selected == item.id, onClick = { selected = item.id }, role = Role.RadioButton).padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(selected == item.id, onClick = null)
                            Column(Modifier.padding(start = 12.dp)) {
                                Text("${item.title}: $have of ${item.target}")
                                LinearProgressIndicator(progress = { (have / item.target.toFloat()).coerceIn(0f, 1f) }, Modifier.fillMaxWidth(0.6f))
                            }
                        }
                    }
                    HorizontalDivider()
                    Text(step.title, style = MaterialTheme.typography.titleMedium)
                    Text(step.instruction, style = MaterialTheme.typography.bodyMedium)
                    if (step.id == "enroll") Text("Phrase: “${ENROLLMENT_PHRASES[(counts[step.condition] ?: 0) % ENROLLMENT_PHRASES.size]}”", style = MaterialTheme.typography.bodyLarge)
                    if (step.nonOwner) {
                        Row(verticalAlignment = Alignment.Top) {
                            Checkbox(consent, { consent = it })
                            Text("This person has agreed to be recorded for this test and knows the clips are deleted afterwards.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 12.dp))
                        }
                        OutlinedTextField(alias, { alias = cleanAlias(it) }, Modifier.fillMaxWidth(), label = { Text("Alias (letters and digits)") }, singleLine = true)
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Button({ if (recorder.recording) recorder.cancel() else recorder.begin() }, enabled = !vi.busy && (!step.nonOwner || consent)) { Text(if (recorder.recording) "Stop" else "Record a clip") }
                        if (recorder.recording) LinearProgressIndicator(progress = { recorder.level }, Modifier.weight(1f))
                    }
                    recorder.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                    HorizontalDivider()
                    Text("When you are done", style = MaterialTheme.typography.titleMedium)
                    Text("On your computer: download the dataset from the web Overview (owner recognition → export) or let the tool fetch it, then run tools/voice_identity_benchmark.py. It reports the error rates; you decide the threshold.", style = MaterialTheme.typography.bodySmall)
                    OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth(), label = { Text("Password, to delete everything") }, singleLine = true, visualTransformation = PasswordVisualTransformation())
                    OutlinedButton({ vi.deleteGvClips(password); password = "" }, enabled = !vi.busy && password.isNotBlank()) { Text("Delete all evaluation clips and switch recording off") }
                }
                Text("", Modifier.padding(24.dp))
            }
        }
    }
}
