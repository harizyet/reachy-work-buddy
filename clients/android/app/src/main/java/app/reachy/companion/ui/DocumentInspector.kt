package app.reachy.companion.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import app.reachy.companion.DocumentsModel
import app.reachy.companion.data.DocumentItem
import app.reachy.companion.data.InspectBlock
import app.reachy.companion.data.InspectPage
import app.reachy.companion.data.Part
import app.reachy.companion.data.TIER_LABEL
import app.reachy.companion.data.blockAt
import app.reachy.companion.data.describeBlock
import app.reachy.companion.data.parseExtracted

private fun decode(bytes: ByteArray?): ImageBitmap? = bytes?.let { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() }

/**
 * How the document was read, one page at a time: MinerU's picture of the original beside (here: switchable with) what it extracted, with the
 * blocks it found and where. On a phone the two views are a toggle, not a split. What is shown is derived extraction; the original is what counts.
 */
@Composable
fun DocumentInspector(docs: DocumentsModel, doc: DocumentItem, startPage: Int) {
    var page by rememberSaveable(doc.id) { mutableStateOf(startPage) }
    var showOriginal by rememberSaveable(doc.id) { mutableStateOf(true) }
    var zoom by remember { mutableFloatStateOf(1f) }
    var selected by remember { mutableStateOf<InspectBlock?>(null) }
    LaunchedEffect(startPage) { page = startPage }
    // A different tier or a re-read changes what a page holds, so the page is loaded again when the document's state changes.
    LaunchedEffect(doc.id, page, doc.tier, doc.state) { selected = null; docs.inspect(page) }
    val data = docs.inspectPage
    val total = data?.pageCount ?: doc.pageCount ?: 1
    val picture = remember(docs.pageImage) { decode(docs.pageImage) }
    val hasPicture = data?.pageImage == true && picture != null

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton({ page -= 1 }, enabled = page > 1) { Icon(Icons.AutoMirrored.Filled.KeyboardArrowLeft, "Previous page") }
            Text("Page $page of $total", style = MaterialTheme.typography.labelLarge)
            IconButton({ page += 1 }, enabled = page < total) { Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, "Next page") }
            Box(Modifier.weight(1f))
            FilterChip(showOriginal, { showOriginal = true }, { Text("Original") })
            FilterChip(!showOriginal, { showOriginal = false }, { Text("Extracted") }, modifier = Modifier.padding(start = 6.dp))
        }
        if (docs.inspecting) LinearProgressIndicator(Modifier.fillMaxWidth())
        docs.inspectError?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 16.dp)) }
        if (data != null) {
            Text(
                "Read at ${TIER_LABEL[data.tier] ?: data.tier}. This is the extraction; the original is what counts.",
                style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(horizontal = 16.dp, vertical = 2.dp),
            )
            if (showOriginal) OriginalView(data, picture, hasPicture, zoom, { zoom = it }, selected) { selected = it }
            else ExtractedView(data) { selected = it }
        }
    }
    selected?.let { block ->
        BlockDialog(block, docs.blockImage?.takeIf { it.first == block.block }?.second, { docs.showBlock(block.block) }) { selected = null; docs.hideBlock() }
    }
}

@Composable
private fun OriginalView(data: InspectPage, picture: ImageBitmap?, hasPicture: Boolean, zoom: Float, onZoom: (Float) -> Unit, selected: InspectBlock?, onSelect: (InspectBlock) -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        if (!hasPicture || picture == null) {
            Text(
                if (data.pageImage) "The picture of this page could not be loaded." else "MinerU has no picture of the original for this kind of file (for example a Word document). Switch to Extracted to see what was read.",
                modifier = Modifier.padding(16.dp),
            )
            return@Column
        }
        Row(Modifier.padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Zoom", style = MaterialTheme.typography.labelMedium)
            for (z in listOf(1f, 2f, 3f)) FilterChip(zoom == z, { onZoom(z) }, { Text("${z.toInt()}×") })
            Text("Tap a box for details", style = MaterialTheme.typography.labelSmall)
        }
        BoxWithConstraints(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
            val width = maxWidth * zoom
            Box(
                Modifier.width(width).padding(8.dp).border(1.dp, MaterialTheme.colorScheme.outline)
                    .pointerInput(data.blocks) {
                        detectTapGestures { tap ->
                            blockAt(data.blocks, (tap.x / size.width).toDouble(), (tap.y / size.height).toDouble())?.let(onSelect)
                        }
                    },
            ) {
                Image(picture, "Page ${data.page} of the original", Modifier.fillMaxWidth(), contentScale = ContentScale.FillWidth)
                Canvas(Modifier.matchParentSize()) {
                    for (b in data.blocks) {
                        val box = b.bbox?.takeIf { it.size == 4 } ?: continue
                        val hot = selected?.block == b.block
                        val color = if (hot) Color(0xFFD81B60) else if (b.type.contains("table")) Color(0xFF2E7D32) else Color(0xFF1565C0)
                        drawRect(
                            color.copy(alpha = if (hot) 1f else 0.7f),
                            Offset((box[0] * size.width).toFloat(), (box[1] * size.height).toFloat()),
                            Size(((box[2] - box[0]) * size.width).toFloat(), ((box[3] - box[1]) * size.height).toFloat()),
                            style = Stroke(width = if (hot) 4f else 2f),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ExtractedView(data: InspectPage, onBlock: (InspectBlock) -> Unit) {
    val parts = remember(data.markdown) { parseExtracted(data.markdown) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (parts.isEmpty()) Text("Nothing was extracted from this page.")
        SelectionContainer {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                for (part in parts) when (part) {
                    is Part.Heading -> Text(part.text, style = if (part.level <= 1) MaterialTheme.typography.titleLarge else MaterialTheme.typography.titleMedium)
                    is Part.Paragraph -> Text(part.text, style = MaterialTheme.typography.bodyMedium)
                    is Part.Table -> TableView(part.rows)
                }
            }
        }
        HorizontalDivider()
        Text("Blocks on this page (${data.blocks.size})", style = MaterialTheme.typography.titleSmall)
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            for (b in data.blocks) AssistChip({ onBlock(b) }, { Text("${b.block}. ${b.type.replace('_', ' ')}") })
        }
    }
}

@Composable
private fun TableView(rows: List<List<String>>) {
    val columns = rows.maxOf { it.size }
    Column(Modifier.horizontalScroll(rememberScrollState()).border(1.dp, MaterialTheme.colorScheme.outline)) {
        rows.forEachIndexed { r, row ->
            Row {
                for (c in 0 until columns) Text(
                    row.getOrElse(c) { "" }, Modifier.width(140.dp).border(0.5.dp, MaterialTheme.colorScheme.outlineVariant).padding(6.dp),
                    style = if (r == 0) MaterialTheme.typography.labelLarge else MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun BlockDialog(block: InspectBlock, crop: ByteArray?, onShowCrop: () -> Unit, onClose: () -> Unit) {
    val image = remember(crop) { decode(crop) }
    AlertDialog(
        onClose, title = { Text("Block ${block.block}: ${block.type.replace('_', ' ')}") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(describeBlock(block))
                if (image != null) Image(image, "Crop of block ${block.block}", Modifier.fillMaxWidth(), contentScale = ContentScale.FillWidth)
                else TextButton(onShowCrop) { Text("Show this block as MinerU cut it out") }
            }
        },
        confirmButton = { TextButton(onClose) { Text("Close") } },
    )
}
