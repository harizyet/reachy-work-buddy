package app.reachy.companion.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.snapping.rememberSnapFlingBehavior
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.reachy.companion.AppViewModel
import app.reachy.companion.data.Alarm
import app.reachy.companion.data.SHORT_DAYS
import app.reachy.companion.data.clockOf
import app.reachy.companion.data.isOn
import app.reachy.companion.data.listedAlarms
import app.reachy.companion.data.repeatText
import androidx.compose.material3.ExperimentalMaterial3Api as Exp

/** An iPhone-Clock-style alarm list: big times with on/off switches, Edit to delete, + to add. */
@Composable
fun AlarmsScreen(model: AppViewModel, modifier: Modifier = Modifier) {
    ReadableWidth(modifier, 640) { AlarmsContent(model) }
}

@Composable
private fun AlarmsContent(model: AppViewModel) {
    var editing by remember { mutableStateOf(false) }
    var sheetFor by remember { mutableStateOf<Alarm?>(null) }
    var adding by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { model.loadAlarms() }
    val alarms = listedAlarms(model.alarms)
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            TextButton({ editing = !editing }) { Text(if (editing) "Done" else "Edit") }
            Text("Alarms", Modifier.weight(1f).padding(start = 8.dp), style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            FilledIconButton({ adding = true }) { Icon(Icons.Default.Add, "Add alarm") }
        }
        ErrorLine(model.listError)
        if (alarms.isEmpty()) Text("No alarms.", Modifier.padding(16.dp))
        LazyColumn(Modifier.fillMaxSize()) {
            items(alarms, key = { it.id }) { alarm ->
                val on = isOn(alarm)
                val clock = clockOf(alarm)
                val repeat = repeatText(alarm.repeat)
                val sub = listOf(alarm.label, repeat).filter { it.isNotBlank() }.joinToString(", ")
                val stationName = model.stations.firstOrNull { it.id == alarm.stationId }?.name
                val extra = listOfNotNull(stationName, if (alarm.volume != 100) "${alarm.volume}% volume" else null).joinToString(" · ")
                Column {
                    HorizontalDivider()
                    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        if (editing) FilledIconButton(
                            { model.deleteAlarm(alarm.id) }, Modifier.size(28.dp),
                            colors = androidx.compose.material3.IconButtonDefaults.filledIconButtonColors(containerColor = MaterialTheme.colorScheme.error),
                        ) { Icon(Icons.Default.Remove, "Delete alarm ${alarm.label}", Modifier.size(18.dp)) }
                        Column(Modifier.weight(1f).clickable { sheetFor = alarm }.padding(start = if (editing) 12.dp else 0.dp).alpha(if (on) 1f else 0.5f)) {
                            Row(verticalAlignment = Alignment.Bottom) {
                                Text(clock.text, fontSize = 48.sp, fontWeight = FontWeight.Light)
                                Text(clock.suffix, Modifier.padding(start = 4.dp, bottom = 8.dp), fontSize = 20.sp)
                            }
                            Text(sub, style = MaterialTheme.typography.bodyMedium)
                            if (extra.isNotEmpty()) Text(extra, style = MaterialTheme.typography.bodySmall)
                            if (alarm.status == "fired" && !alarm.delivery.isNullOrBlank()) Text("last: ${alarm.delivery}", style = MaterialTheme.typography.bodySmall)
                        }
                        Switch(on, { model.setAlarmOn(alarm.id, it) })
                    }
                }
            }
        }
    }
    if (adding) AlarmSheet(model, null) { adding = false }
    sheetFor?.let { AlarmSheet(model, it) { sheetFor = null } }
}

@OptIn(Exp::class)
@Composable
private fun AlarmSheet(model: AppViewModel, alarm: Alarm?, onClose: () -> Unit) {
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val initial = remember { alarm?.let { clockOf(it) } ?: java.time.LocalTime.now().plusMinutes(1).let { clockOf(it.hour, it.minute) } }
    var hour by remember { mutableStateOf(initial.hour12) }
    var minute by remember { mutableStateOf(initial.minute) }
    var pm by remember { mutableStateOf(initial.pm) }
    var days by remember { mutableStateOf(alarm?.repeat?.toSet() ?: emptySet()) }
    var label by remember { mutableStateOf(alarm?.label ?: "Alarm") }
    var stationId by remember { mutableStateOf(alarm?.stationId) }
    var volume by remember { mutableStateOf((alarm?.volume ?: 100).toFloat()) }
    var soundMenu by remember { mutableStateOf(false) }
    ModalBottomSheet(onClose, sheetState = state) {
        Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 24.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClose) { Text("Cancel") }
                Text(if (alarm == null) "Add Alarm" else "Edit Alarm", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                TextButton(
                    {
                        val wire = app.reachy.companion.data.ClockTime(hour, minute, pm).wire
                        model.saveAlarm(alarm?.id, label.ifBlank { "Alarm" }, wire, days.sorted(), stationId, volume.toInt())
                        onClose()
                    },
                ) { Text("Save", fontWeight = FontWeight.Bold) }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                Wheel((1..12).map { it.toString() }, hour - 1, Modifier.width(80.dp)) { hour = it + 1 }
                Wheel((0..59).map { "%02d".format(it) }, minute, Modifier.width(80.dp)) { minute = it }
                Wheel(listOf("AM", "PM"), if (pm) 1 else 0, Modifier.width(80.dp)) { pm = it == 1 }
            }
            Column(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(12.dp)).padding(horizontal = 16.dp, vertical = 4.dp)) {
                Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("Repeat", Modifier.weight(1f))
                    Text(repeatText(days).ifEmpty { "Never" }, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
                }
                Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    SHORT_DAYS.forEachIndexed { index, name ->
                        FilterChip(index in days, { days = if (index in days) days - index else days + index }, { Text(name.take(1), maxLines = 1) }, Modifier.weight(1f))
                    }
                }
                HorizontalDivider()
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("Label")
                    TextField(
                        label, { label = it.take(200) }, Modifier.weight(1f), singleLine = true,
                        textStyle = androidx.compose.ui.text.TextStyle(textAlign = androidx.compose.ui.text.style.TextAlign.End),
                        colors = TextFieldDefaults.colors(focusedContainerColor = androidx.compose.ui.graphics.Color.Transparent, unfocusedContainerColor = androidx.compose.ui.graphics.Color.Transparent),
                    )
                }
                HorizontalDivider()
                Box {
                    Row(Modifier.fillMaxWidth().clickable { soundMenu = true }.padding(vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("Sound", Modifier.weight(1f))
                        Text(model.stations.firstOrNull { it.id == stationId }?.name ?: "Chime", color = MaterialTheme.colorScheme.outline)
                    }
                    DropdownMenu(soundMenu, { soundMenu = false }) {
                        DropdownMenuItem({ Text("Chime (no station)") }, { stationId = null; soundMenu = false })
                        model.stations.forEach { s -> DropdownMenuItem({ Text(s.name) }, { stationId = s.id; soundMenu = false }) }
                    }
                }
                HorizontalDivider()
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("Volume")
                    Slider(volume, { volume = (it / 10).toInt() * 10f }, Modifier.weight(1f).padding(horizontal = 12.dp), valueRange = 10f..400f)
                    Text("${volume.toInt()}%", style = MaterialTheme.typography.bodySmall)
                }
            }
            if (alarm != null) Button(
                { model.deleteAlarm(alarm.id); onClose() }, Modifier.fillMaxWidth().padding(top = 16.dp),
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.surfaceVariant, contentColor = MaterialTheme.colorScheme.error),
            ) { Text("Delete Alarm") }
        }
    }
}

private val ItemHeight = 44.dp

/** A scrolling picker that snaps to one item, reporting the chosen index when scrolling settles. */
@Composable
private fun Wheel(items: List<String>, selected: Int, modifier: Modifier = Modifier, onSelected: (Int) -> Unit) {
    val state = rememberLazyListState(initialFirstVisibleItemIndex = selected.coerceIn(0, items.lastIndex))
    val centred by remember { derivedStateOf { (state.firstVisibleItemIndex + if (state.firstVisibleItemScrollOffset > 60) 1 else 0).coerceIn(0, items.lastIndex) } }
    LaunchedEffect(state.isScrollInProgress) { if (!state.isScrollInProgress) onSelected(centred) }
    Box(modifier.height(ItemHeight * 5), contentAlignment = Alignment.Center) {
        Box(Modifier.fillMaxWidth().height(ItemHeight).background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(10.dp)))
        LazyColumn(
            state = state, flingBehavior = rememberSnapFlingBehavior(state),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(vertical = ItemHeight * 2),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            items(items.size) { index ->
                Box(Modifier.height(ItemHeight).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    Text(items[index], fontSize = 26.sp, fontWeight = if (index == centred) FontWeight.SemiBold else FontWeight.Normal, modifier = Modifier.alpha(if (index == centred) 1f else 0.5f))
                }
            }
        }
    }
}
