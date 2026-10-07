package app.reachy.companion.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
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
import app.reachy.companion.data.tailscaleActive
import kotlinx.coroutines.delay

const val TAILSCALE_WARNING =
    "Tailscale is not connected. Reachy may be unreachable, and the app talks to your hub over plain HTTP, " +
        "so your password and messages would cross this network unencrypted. Open Tailscale and connect first."

/** Re-checks every few seconds so the warning clears as soon as Tailscale connects. */
@Composable
fun rememberTailscaleActive(): Boolean {
    var active by remember { mutableStateOf(tailscaleActive()) }
    LaunchedEffect(Unit) { while (true) { delay(3000); active = tailscaleActive() } }
    return active
}

@Composable
fun TailscaleBanner(modifier: Modifier = Modifier) {
    var dismissed by remember { mutableStateOf(false) }
    if (rememberTailscaleActive() || dismissed) return
    Surface(color = MaterialTheme.colorScheme.errorContainer, modifier = modifier.fillMaxWidth()) {
        Row(Modifier.padding(start = 16.dp, end = 4.dp, top = 4.dp, bottom = 4.dp)) {
            Text(TAILSCALE_WARNING, Modifier.weight(1f).padding(vertical = 8.dp), style = MaterialTheme.typography.bodySmall)
            TextButton({ dismissed = true }) { Text("Dismiss") }
        }
    }
}

@Composable
fun TailscaleDialog(onCancel: () -> Unit, onContinue: () -> Unit) {
    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text("Tailscale is not connected") },
        text = { Column { Text(TAILSCALE_WARNING) } },
        confirmButton = { TextButton(onContinue) { Text("Sign in anyway") } },
        dismissButton = { TextButton(onCancel) { Text("Cancel") } },
    )
}
