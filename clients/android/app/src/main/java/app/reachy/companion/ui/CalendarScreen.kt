package app.reachy.companion.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel
import app.reachy.companion.data.CalendarItem
import app.reachy.companion.data.Marker
import app.reachy.companion.data.classLabel
import app.reachy.companion.data.dayMarkers
import app.reachy.companion.data.dayTime
import app.reachy.companion.data.eventsOn
import app.reachy.companion.data.monthGrid
import app.reachy.companion.data.reminderStatus
import app.reachy.companion.data.scheduleTitle
import app.reachy.companion.data.syncLines
import app.reachy.companion.data.upcomingMeetings
import kotlinx.coroutines.delay
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale

/** The Calendar tab: month, the selected day's agenda, upcoming meetings and what the sync is doing. The data is one revision of the hub's calendar (ADR 0035). */
@Composable
fun CalendarScreen(model: AppViewModel, modifier: Modifier = Modifier) {
    LaunchedEffect(Unit) {
        model.openCalendar()
        while (true) { delay(20_000); model.loadCalendar() }  // the hub is asked again while this tab is open: a new revision shows up without a manual refresh
    }
    LaunchedEffect(model.calendarMonth) { model.loadCalendar() }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis(); delay(30_000) } }

    val view = model.calendarView
    val zone = ZoneId.systemDefault()
    val events = view?.events.orEmpty()
    val today = LocalDate.now()
    val grid = monthGrid(model.calendarMonth)
    val day = eventsOn(events, model.calendarDay, zone)
    val upcoming = upcomingMeetings(events, now, zone)

    LazyColumn(modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Spacer8() }
        if (view == null) item { Text("Loading the calendar…", style = MaterialTheme.typography.bodyMedium) }
        if (view != null && !view.feed.configured) item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("No calendar set up", style = MaterialTheme.typography.titleMedium)
                    Text("Add the link to your calendar, or upload an .ics file, in the web control panel under Settings > Accounts.", style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
        if (view != null) item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp).semantics { contentDescription = "Sync status" }, verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text("Sync status", style = MaterialTheme.typography.titleSmall)
                    for (line in syncLines(view, model.calendarCheckedMs, model.calendarOffline, now)) {
                        Row { Text(line.label + ": ", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline); Text(line.value, style = MaterialTheme.typography.bodySmall) }
                    }
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Button({ model.refreshCalendarSource() }, enabled = !model.calendarRefreshing && view.feed.configured) { Text(if (model.calendarRefreshing) "Refreshing…" else "Refresh") }
                        model.calendarMessage?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary) }
                    }
                }
            }
        }
        item {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton({ model.calendarMonth = model.calendarMonth.minusMonths(1) }) { Text("‹") }
                    Text(model.calendarMonth.month.getDisplayName(TextStyle.FULL, Locale.getDefault()) + " " + model.calendarMonth.year, Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                    TextButton({ model.calendarMonth = java.time.YearMonth.from(today); model.calendarDay = today }) { Text("Today") }
                    TextButton({ model.calendarMonth = model.calendarMonth.plusMonths(1) }) { Text("›") }
                }
                Row(Modifier.fillMaxWidth()) {
                    for (d in listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")) Text(d, Modifier.weight(1f), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                }
                for (week in grid.chunked(7)) Row(Modifier.fillMaxWidth()) {
                    for (date in week) DayCell(date, date == model.calendarDay, date == today, date.month == model.calendarMonth.month, dayMarkers(events, date, zone), Modifier.weight(1f)) { model.calendarDay = date }
                }
                Text("● meeting   ■ leave   ○ other events", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
            }
        }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("Upcoming meetings", style = MaterialTheme.typography.titleSmall)
                    if (upcoming.isEmpty()) Text(if (view?.feed?.configured == true) "No upcoming meetings." else "Nothing to show until a calendar is set up.", style = MaterialTheme.typography.bodySmall)
                    for (e in upcoming) EventRow(e, java.time.OffsetDateTime.parse(e.start).atZoneSameInstant(zone).toLocalDate(), zone)
                }
            }
        }
        item {
            Column {
                Text(model.calendarDay.format(DateTimeFormatter.ofPattern("EEEE d MMMM yyyy")), style = MaterialTheme.typography.titleMedium, modifier = Modifier.semantics { contentDescription = "Agenda" })
                if (day.isEmpty()) Text(if (view?.feed?.configured == true) "Nothing on this day." else "No calendar is set up.", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 4.dp))
            }
        }
        items(day.size) { i -> EventRow(day[i], model.calendarDay, zone) }
        item { Spacer8() }
    }
}

@Composable
private fun Spacer8() = Box(Modifier.size(4.dp))

@Composable
private fun DayCell(date: LocalDate, selected: Boolean, today: Boolean, inMonth: Boolean, markers: List<Marker>, modifier: Modifier, onClick: () -> Unit) {
    val primary = MaterialTheme.colorScheme.primary
    val label = date.format(DateTimeFormatter.ofPattern("EEEE d MMMM")) + if (markers.isNotEmpty()) ", " + markers.joinToString { it.name.lowercase() } else ""
    Box(
        modifier.padding(2.dp).aspectRatio(1f).clip(RoundedCornerShape(8.dp))
            .background(if (selected) primary else Color.Transparent)
            .clickable(onClick = onClick).semantics { contentDescription = label },
        contentAlignment = Alignment.Center,
    ) {
        val ink = if (selected) Color.White else if (inMonth) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.outline
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(date.dayOfMonth.toString(), color = ink, style = if (today) MaterialTheme.typography.titleSmall else MaterialTheme.typography.bodyMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(2.dp), modifier = Modifier.size(width = 24.dp, height = 6.dp)) {
                if (Marker.Meeting in markers) Box(Modifier.size(5.dp).clip(CircleShape).background(ink))
                if (Marker.Leave in markers) Box(Modifier.size(5.dp).background(ink))
                if (Marker.Other in markers) Box(Modifier.size(5.dp).clip(CircleShape).border(1.dp, ink, CircleShape))
            }
        }
    }
}

@Composable
private fun EventRow(e: CalendarItem, day: LocalDate, zone: ZoneId) {
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(classLabel(e), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
            Text(scheduleTitle(e) + if (e.status == "tentative") " (tentative)" else "", style = MaterialTheme.typography.bodyMedium)
        }
        Text(dayTime(e, day, zone), style = MaterialTheme.typography.bodySmall)
        if (!e.location.isNullOrBlank() && !e.redacted) Text(e.location, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
        Text(reminderStatus(e) + if (e.basis == "owner") " · classification set by you" else "", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
    }
}
