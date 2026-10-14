package app.reachy.companion.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel
import app.reachy.companion.data.Choice
import app.reachy.companion.data.Meeting
import app.reachy.companion.data.Mode
import app.reachy.companion.data.SamplePool
import app.reachy.companion.data.SpeakerSample
import app.reachy.companion.data.decisionsFor
import app.reachy.companion.data.initialChoice
import app.reachy.companion.data.poolOf
import app.reachy.companion.data.sampleLabel

/**
 * Identify Speakers (Phase 54): listen to a few clear stretches of the recording per detected speaker and say who they are. Names, Unknown and Skip are all optional; nothing is
 * saved until Save. Reachy does not recognise voices: it only picked stretches where one detected speaker was talking. [onShow] jumps to that moment in the transcript's player.
 */
@Composable
fun IdentifySpeakers(model: AppViewModel, meeting: Meeting, onShow: (Double) -> Unit, modifier: Modifier = Modifier) {
    LaunchedEffect(meeting.id) { model.loadIdentify() }
    val screen = model.identify
    val player = model.player
    // The player's own refresh loop stops a sample at its end; it only runs while something plays.
    LaunchedEffect(player.playing, player.meetingId) {
        while (player.playing) { player.refresh(); kotlinx.coroutines.delay(200) }
    }
    if (screen == null || screen.meetingId != meeting.id) {
        Text(model.listError ?: "Loading the speakers…", modifier.padding(16.dp))
        return
    }
    val choices = remember(screen.fingerprint, screen.speakers.map { it.identity }) { mutableStateMapOf<String, Choice>().apply { screen.speakers.forEach { put(it.label, initialChoice(it)) } } }
    val pools = remember(screen.fingerprint) { mutableStateMapOf<String, SamplePool>().apply { screen.speakers.forEach { put(it.label, poolOf(it)) } } }
    val decisions = decisionsFor(screen.speakers, choices)
    var playingKey by remember { mutableStateOf<String?>(null) }

    LazyColumn(modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Text(
                "Listen to a few stretches of the recording from each speaker, then say who they are. Names you save appear in the transcript, summaries and analysis. " +
                    "You can skip anyone you are unsure of. Reachy does not recognise voices: it only picked clear stretches where one detected speaker was talking.",
                style = MaterialTheme.typography.bodySmall,
            )
            if (screen.needsReview) Text(
                "Speaker detection was run again and the speakers changed, so the names you gave before were not applied" +
                    (screen.superseded?.identities?.takeIf { it.isNotEmpty() }?.let { " (they were: " + it.entries.joinToString(", ") { (label, i) -> "$label ${i.name?.let { n -> "= $n" } ?: i.status}" } + ")" } ?: "") +
                    ". Please check each speaker below.",
                Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall, color = GapText,
            )
            if (meeting.staleOutputs.isNotEmpty()) Text(
                "The ${meeting.staleOutputs.joinToString(" and ")} was written under different speaker names. Rerun it after you save.",
                Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall, color = GapText,
            )
        }
        items(screen.speakers, key = { it.label }) { card ->
            val choice = choices[card.label] ?: Choice()
            val pool = pools[card.label] ?: poolOf(card)
            Card(Modifier.fillMaxWidth().semantics { contentDescription = card.displayName }) {
                Column(Modifier.padding(12.dp)) {
                    Text(card.displayName, style = MaterialTheme.typography.titleSmall)
                    Text("${card.label} · ${card.seconds.toInt()} s of speech · ${card.lines} line${if (card.lines == 1) "" else "s"}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
                    card.reason?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = GapText) }
                    if (pool.shown.isEmpty() && card.reason == null) Text("No sample is available for this speaker.", style = MaterialTheme.typography.bodySmall)
                    pool.shown.forEach { sample ->
                        val key = "${card.label}@${sample.start}"
                        val active = playingKey == key && player.playing && player.rangeEndMs >= 0
                        SampleRow(
                            name = card.displayName, sample = sample, active = active,
                            onPlay = {
                                if (active) { player.toggle(); playingKey = null }
                                else { playingKey = key; model.playSample(meeting.id, sample.start, sample.end) }
                            },
                            onShow = { onShow(sample.start) },
                            onAnother = if (pool.spare.isNotEmpty()) ({ if (playingKey == key && player.playing) player.toggle(); playingKey = null; pools[card.label] = pool.another(sample) }) else null,
                        )
                    }
                    OutlinedTextField(
                        value = if (choice.mode == Mode.NAME) choice.name else "",
                        onValueChange = { choices[card.label] = if (it.isEmpty()) Choice() else Choice(Mode.NAME, it.take(60)) },
                        label = { Text("Who is ${card.displayName}?") }, singleLine = true,
                        keyboardOptions = KeyboardOptions.Default,
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    )
                    val known = screen.suggestions.filter { it.contains(choice.name.trim(), ignoreCase = true) && !it.equals(choice.name.trim(), ignoreCase = true) }.take(8)
                    if (known.isNotEmpty()) Row(Modifier.horizontalScroll(rememberScrollState()).padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        known.forEach { name -> AssistChip({ choices[card.label] = Choice(Mode.NAME, name) }, { Text(name) }) }
                    }
                    Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(choice.mode == Mode.UNKNOWN, { choices[card.label] = Choice(Mode.UNKNOWN) }, { Text("Unknown") })
                        FilterChip(choice.mode == Mode.SKIPPED, { choices[card.label] = Choice(Mode.SKIPPED) }, { Text("Skip") })
                        if (card.identity != null) TextButton({ choices[card.label] = Choice() }) { Text(if (card.identity.status == "named") "Remove name" else "Undo") }
                    }
                    card.identity?.let {
                        Text(if (it.status == "named") "Saved as ${it.name}." else "Saved as ${it.status}.", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
                    }
                }
            }
        }
        item {
            Button({ model.saveIdentify(decisions) }, enabled = decisions.isNotEmpty() && !model.identifySaving, modifier = Modifier.fillMaxWidth()) {
                Text(if (decisions.isEmpty()) "Save" else "Save ${decisions.size} change${if (decisions.size == 1) "" else "s"}")
            }
            model.identifyNote?.let { Text(it, Modifier.padding(top = 4.dp), style = MaterialTheme.typography.bodySmall) }
        }
    }
}

@Composable
private fun SampleRow(name: String, sample: SpeakerSample, active: Boolean, onPlay: () -> Unit, onShow: () -> Unit, onAnother: (() -> Unit)?) {
    val label = sampleLabel(sample)
    Column(Modifier.padding(top = 4.dp)) {
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            IconButton(onPlay, Modifier.semantics { contentDescription = "${if (active) "Pause" else "Play"} $name sample at $label" }) {
                Icon(if (active) Icons.Default.Pause else Icons.Default.PlayArrow, null)
            }
            Text(label, style = MaterialTheme.typography.labelLarge)
            if (sample.quality == "low") Text("  Unclear: ${sample.notes.joinToString("; ").ifBlank { "low quality" }}", style = MaterialTheme.typography.labelSmall, color = GapText)
        }
        if (sample.text.isNotBlank()) Text("“${sample.text}”", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
        Row {
            TextButton(onShow, Modifier.semantics { contentDescription = "Show $label in the recording" }) { Text("In recording", style = MaterialTheme.typography.labelSmall) }
            if (onAnother != null) TextButton(onAnother, Modifier.semantics { contentDescription = "Another sample instead of $label" }) { Text("Another sample", style = MaterialTheme.typography.labelSmall) }
        }
    }
}
