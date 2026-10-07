package app.reachy.companion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import app.reachy.companion.ui.ConnectScreen
import app.reachy.companion.ui.Shell

private val colors = lightColorScheme(primary = Color(0xFF2F5D8A), secondary = Color(0xFF3F7D6B), tertiary = Color(0xFFB5543C))

class MainActivity : ComponentActivity() {
    private val model by viewModels<AppViewModel>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme(colorScheme = colors) { Surface(Modifier.fillMaxSize()) { Root(model) } } }
    }
}

@Composable
private fun Root(model: AppViewModel) {
    when (model.session) {
        Session.Checking -> Box(Modifier.fillMaxSize(), Alignment.Center) { CircularProgressIndicator() }
        Session.SignedOut -> ConnectScreen(model)
        Session.SignedIn -> Shell(model)
    }
}
