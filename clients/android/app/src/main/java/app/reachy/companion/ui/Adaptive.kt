package app.reachy.companion.ui

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.width
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.Box

/** A window at least this wide (an unfolded Pixel Fold, a tablet, a phone in landscape) gets a side rail and two panes. */
private const val WIDE_DP = 600

/** Follows the window, so folding or unfolding re-lays the screens out in place (the activity handles the change itself). */
@Composable
fun isWide(): Boolean = LocalConfiguration.current.screenWidthDp >= WIDE_DP

/** A list on the left and its detail on the right; on a narrow window callers show one or the other instead. */
@Composable
fun TwoPane(modifier: Modifier = Modifier, listWidth: Int = 360, list: @Composable () -> Unit, detail: @Composable () -> Unit) {
    Row(modifier.fillMaxSize()) {
        Box(Modifier.width(listWidth.dp).fillMaxHeight()) { list() }
        VerticalDivider()
        Box(Modifier.weight(1f).fillMaxHeight()) { detail() }
    }
}

/** Keeps single-column content readable on a wide window instead of stretching it edge to edge. */
@Composable
fun ReadableWidth(modifier: Modifier = Modifier, maxWidth: Int = 720, content: @Composable () -> Unit) {
    if (!isWide()) { Box(modifier.fillMaxSize()) { content() }; return }
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) { Box(Modifier.widthIn(max = maxWidth.dp).fillMaxSize()) { content() } }
}
