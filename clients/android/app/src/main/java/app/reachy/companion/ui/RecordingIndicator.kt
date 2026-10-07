package app.reachy.companion.ui

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel
import kotlinx.coroutines.delay

private val RecordingRed = Color(0xFFC62828)

@Composable
fun PulsingDot(modifier: Modifier = Modifier, size: Int = 10) {
    val alpha by rememberInfiniteTransition(label = "recording").animateFloat(
        1f, 0.25f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "pulse",
    )
    androidx.compose.foundation.layout.Box(modifier.size(size.dp).alpha(alpha).background(RecordingRed, CircleShape))
}

/** Shown on every tab while a meeting is being recorded, with a one-tap stop. */
@Composable
fun RecordingBar(model: AppViewModel) {
    if (!model.recording) return
    var elapsed by remember { mutableLongStateOf(0) }
    LaunchedEffect(model.recordingStartedAt) {
        while (true) { elapsed = (System.currentTimeMillis() - model.recordingStartedAt) / 1000; delay(500) }
    }
    Surface(color = RecordingRed, contentColor = Color.White, modifier = Modifier.fillMaxWidth().semantics { contentDescription = "Recording in progress" }) {
        Row(Modifier.padding(start = 16.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            PulsingDot(Modifier.padding(end = 10.dp))
            Text("Recording meeting  ${clock(elapsed.toDouble())}", Modifier.weight(1f), style = MaterialTheme.typography.labelLarge)
            TextButton({ model.stopRecording() }) { Text("Stop and save", color = Color.White) }
        }
    }
}
