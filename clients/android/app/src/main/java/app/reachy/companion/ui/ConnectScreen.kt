package app.reachy.companion.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel

@Composable
fun ConnectScreen(model: AppViewModel) {
    var url by remember { mutableStateOf(model.prefs.baseUrl.ifBlank { "http://" }) }
    var user by remember { mutableStateOf(model.prefs.username) }
    var password by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf(false) }
    val tailscale = rememberTailscaleActive()
    Column(
        Modifier.fillMaxSize().safeDrawingPadding().imePadding().padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("Reachy", style = MaterialTheme.typography.displaySmall)
        Text("Connect to your Reachy hub", style = MaterialTheme.typography.bodyLarge)
        Spacer(Modifier.height(24.dp))
        OutlinedTextField(
            url, { url = it }, Modifier.fillMaxWidth(), label = { Text("Hub address") },
            supportingText = { Text("For example http://100.64.0.5:8080/hub (Tailscale)") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
        )
        OutlinedTextField(user, { user = it }, Modifier.fillMaxWidth(), label = { Text("Username") }, singleLine = true)
        OutlinedTextField(
            password, { password = it }, Modifier.fillMaxWidth(), label = { Text("Password") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        )
        model.loginError?.let { Text(it, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(top = 8.dp)) }
        Spacer(Modifier.height(16.dp))
        Button({ if (tailscale || url.trim().startsWith("https://")) model.signIn(url, user, password) else confirm = true }, Modifier.fillMaxWidth(), enabled = !model.loginBusy && user.isNotBlank() && password.isNotEmpty()) {
            Text(if (model.loginBusy) "Connecting…" else "Sign in")
        }
        if (!tailscale) Text(TAILSCALE_WARNING, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 12.dp))
        Text(
            "The password is sent to your hub once and is not stored on the phone.",
            style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 12.dp),
        )
    }
    if (confirm) TailscaleDialog({ confirm = false }, { confirm = false; model.signIn(url, user, password) })
}
