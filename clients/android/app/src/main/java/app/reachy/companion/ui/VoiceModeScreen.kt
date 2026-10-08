package app.reachy.companion.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.foundation.selection.selectable
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.TextButton
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.semantics.Role
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlin.math.cos
import kotlin.math.sin

/** What the full-screen voice conversation is doing; the ball animates to match. */
enum class VoicePhase(val caption: String) {
    Listening("Listening…"), Thinking("Thinking…"), Speaking(""), Muted("Microphone is off"),
}

@Composable
fun VoiceModeScreen(
    phase: VoicePhase,
    heard: String,
    level: Float,
    error: String?,
    muted: Boolean,
    phoneVoice: Boolean,
    onPhoneVoice: (Boolean) -> Unit,
    onToggleMute: () -> Unit,
    onClose: () -> Unit,
) {
    Dialog(
        onDismissRequest = onClose,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Box(Modifier.fillMaxSize().background(Color.Black).statusBarsPadding().navigationBarsPadding()) {
            Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally) {
                Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    VoiceBall(phase, level, Modifier.size(260.dp))
                }
                // What is heard while the owner speaks, or the status; replies are spoken, not shown.
                Text(
                    error ?: heard.ifBlank { phase.caption },
                    color = if (error != null) Color(0xFFFF8A80) else Color(0xFFBBBBBB),
                    modifier = Modifier.padding(horizontal = 32.dp).padding(bottom = 24.dp),
                )
            }
            var picking by remember { mutableStateOf(false) }
            IconButton(onClose, Modifier.align(Alignment.TopStart).padding(8.dp)) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back to chat", tint = Color.White) }
            IconButton({ picking = true }, Modifier.align(Alignment.TopEnd).padding(8.dp)) { Icon(Icons.Default.Tune, "Choose Reachy's voice source", tint = Color.White) }
            if (picking) AlertDialog(
                onDismissRequest = { picking = false },
                confirmButton = { TextButton({ picking = false }) { Text("Done") } },
                title = { Text("Voice") },
                text = {
                    Column {
                        VoiceChoice("Reachy", "Streamed from your homelab, the same voice as the robot", !phoneVoice) { onPhoneVoice(false) }
                        VoiceChoice("This phone", "The phone's built-in voice, works without the hub", phoneVoice) { onPhoneVoice(true) }
                    }
                },
            )
            Row(Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(horizontal = 24.dp, vertical = 24.dp), verticalAlignment = Alignment.CenterVertically) {
                RoundButton(onToggleMute) {
                    Icon(if (muted) Icons.Default.MicOff else Icons.Default.Mic, if (muted) "Unmute" else "Mute", tint = Color.White)
                }
                Box(Modifier.weight(1f))
                RoundButton(onClose) { Icon(Icons.Default.Close, "End voice mode", tint = Color.White) }
            }
        }
    }
}

@Composable
private fun VoiceChoice(title: String, detail: String, selected: Boolean, onSelect: () -> Unit) {
    Row(Modifier.fillMaxWidth().selectable(selected, onClick = onSelect, role = Role.RadioButton).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        RadioButton(selected, onClick = null)
        Column(Modifier.padding(start = 12.dp)) { Text(title); Text(detail, style = MaterialTheme.typography.bodySmall) }
    }
}

@Composable
private fun RoundButton(onClick: () -> Unit, content: @Composable () -> Unit) {
    IconButton(onClick, Modifier.size(64.dp).clip(CircleShape).background(Color(0xFF2A2A2A))) { content() }
}

/** A soft blue-and-white sphere: still when muted, swells with the owner's voice, drifts while thinking, ripples while Reachy speaks. */
@Composable
private fun VoiceBall(phase: VoicePhase, level: Float, modifier: Modifier = Modifier) {
    val clock = rememberInfiniteTransition(label = "ball")
    val t by clock.animateFloat(
        0f, (2 * Math.PI).toFloat(),
        infiniteRepeatable(tween(6000, easing = LinearEasing), RepeatMode.Restart), label = "drift",
    )
    val breath by clock.animateFloat(
        0f, 1f,
        infiniteRepeatable(tween(if (phase == VoicePhase.Speaking) 450 else 1400), RepeatMode.Reverse), label = "breath",
    )
    // The size follows the phase; the target is eased so it never jumps between frames.
    val target = when (phase) {
        VoicePhase.Listening -> 1f + level * 0.14f
        VoicePhase.Thinking -> 0.92f + breath * 0.06f
        VoicePhase.Speaking -> 1.0f + breath * 0.12f
        VoicePhase.Muted -> 0.9f
    }
    val size by animateFloatAsState(target, tween(120), label = "size")
    val speed = if (phase == VoicePhase.Speaking) 2f else 1f   // blobs move faster while speaking

    Canvas(modifier.scale(size)) {
        val r = this.size.minDimension / 2f
        val c = center
        val disc = Path().apply { addOval(androidx.compose.ui.geometry.Rect(c, r)) }
        clipPath(disc) {
            drawRect(Brush.verticalGradient(listOf(Color(0xFFE6F8FF), Color(0xFF63B8FF), Color(0xFF0A6CF2)), c.y - r, c.y + r))
            val a = t * speed
            // Bright and deep patches sliding over each other give the cloudy, living look.
            fun blob(color: Color, dx: Float, dy: Float, radius: Float) = drawCircle(
                Brush.radialGradient(listOf(color, Color.Transparent), Offset(c.x + dx * r, c.y + dy * r), radius * r),
                radius * r, Offset(c.x + dx * r, c.y + dy * r),
            )
            blob(Color(0xCCFFFFFF), 0.45f * sin(a), -0.45f + 0.15f * cos(a), 0.75f)
            blob(Color(0xAA1E88FF), -0.4f * cos(a * 1.3f), 0.5f + 0.2f * sin(a), 0.85f)
            blob(Color(0x99BDEBFF), 0.3f * cos(a + 1f), 0.05f * sin(a * 2f), 0.55f)
        }
    }
}
