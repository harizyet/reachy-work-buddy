package app.reachy.companion.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.reachy.companion.DeepReviewController

/** Shown on every screen while Reachy's standard model is unloaded for a deep review. */
@Composable
fun DeepReviewBanner() {
    val job = DeepReviewController.job ?: return
    if (!DeepReviewController.reachyUnavailable) return
    Surface(color = Color(0xFFB26A00), contentColor = Color.White, modifier = Modifier.fillMaxWidth().semantics { contentDescription = "Reachy is unavailable" }) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
            Text("Reachy is unavailable: deep review in progress", style = MaterialTheme.typography.labelLarge)
            val stage = if (job.reachyUnavailable || !job.finished) job.stage else ""
            if (stage.isNotBlank()) Text(stage, style = MaterialTheme.typography.bodySmall)
        }
    }
}
