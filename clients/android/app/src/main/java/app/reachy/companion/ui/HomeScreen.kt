package app.reachy.companion.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel
import app.reachy.companion.data.HomeBrief
import app.reachy.companion.data.HomeEvent
import app.reachy.companion.data.HomeReminder
import app.reachy.companion.data.HomeRef
import app.reachy.companion.data.HomeSnapshot
import app.reachy.companion.data.briefHeadline
import app.reachy.companion.data.briefLabel
import app.reachy.companion.data.clock
import app.reachy.companion.data.dayClock
import app.reachy.companion.data.eventTime
import app.reachy.companion.data.plural
import app.reachy.companion.data.savedCopyLine
import app.reachy.companion.data.stateLine
import app.reachy.companion.data.weatherLines
import kotlinx.coroutines.delay
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/**
 * Home: what is on the owner's plate today, from one read-only snapshot of the hub (docs/phase-51.md). Cards for the schedule, reminders, tasks, suggestions awaiting review and weather;
 * each refreshes on its own and each item opens the screen that already holds it. Offline it shows the copy saved on this phone and says how old it is. Nothing here changes a record.
 */
@Composable
fun HomeScreen(model: AppViewModel, modifier: Modifier = Modifier, onOpen: (HomeRef?) -> Unit) {
    LaunchedEffect(Unit) {
        model.openHome()
        while (true) { delay(30_000); model.loadHome() }  // asked again while Home is open: a new calendar revision, a new suggestion or a done reminder shows up on its own
    }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis(); delay(30_000) } }

    val view = model.homeView
    val wide = isWide()
    val cards: List<@Composable () -> Unit> = if (view == null) emptyList() else listOf(
        { ScheduleCard(model, view, onOpen) }, { RemindersCard(model, view, onOpen) }, { TasksCard(model, view, onOpen) },
        { ReviewsCard(model, view, onOpen) }, { WeatherCard(model, view) },
    )
    ReadableWidth(modifier, maxWidth = 1000) {
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { Header(model, view, now) }
            model.homeBrief?.let { brief -> item { BriefCard(brief, onOpen) { model.closeBrief() } } }
            model.homeBriefError?.let { item { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) } }
            if (view == null) item { Text(if (model.homeLoading) "Loading Home…" else model.homeError ?: "Home is not available yet. It will load when the hub can be reached.", style = MaterialTheme.typography.bodyMedium) }
            if (view?.partial == true) item { Text("▲ Some sources could not be read. The sections that did load are accurate; the others say what is missing.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary) }
            if (wide) items(cards.chunked(2)) { pair ->
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) { for (card in pair) Column(Modifier.weight(1f)) { card() }; if (pair.size == 1) Column(Modifier.weight(1f)) {} }
            } else items(cards.size) { cards[it]() }
            if (view != null) item { QuickActions(view, onOpen) }
            item { Text("Robot, models and services status is in the web control panel under System.", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline, modifier = Modifier.padding(bottom = 12.dp)) }
        }
    }
}

@Composable
private fun Header(model: AppViewModel, view: HomeSnapshot?, now: Long) {
    Column(Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(LocalDate.now().format(DateTimeFormatter.ofPattern("EEEE d MMMM")), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.outline)
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Today", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f).semantics { heading() })
            Button({ model.briefMe() }, enabled = !model.homeBriefBusy && view != null && !view.restricted && !model.homeOffline) { Text(if (model.homeBriefBusy) "Preparing…" else "Brief me on today") }
        }
        val checked = model.homeCheckedMs
        if (model.homeOffline && checked != null) Text(savedCopyLine(checked, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary, modifier = Modifier.semantics { contentDescription = "Offline notice" })
        else if (model.homeOffline) Text("The hub could not be reached and nothing is saved on this phone yet.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary)
        model.homeError?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
    }
}

/** A card for one section: its own Refresh and an honest line for every state a source can be in. */
@Composable
private fun SectionCard(
    title: String, name: String, status: String?, model: AppViewModel, offText: String = "This feature is turned off.", note: String? = null, content: @Composable () -> Unit,
) {
    Card(Modifier.fillMaxWidth().semantics { contentDescription = "$title card" }, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f))) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f).semantics { heading() })
                val busy = name in model.homeBusy
                TextButton({ model.refreshHomeSection(name) }, enabled = !busy, modifier = Modifier.semantics { contentDescription = "Refresh $title" }) { Text(if (busy) "Refreshing…" else "Refresh") }
            }
            note?.let { Text("▲ $it", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary) }
            val line = stateLine(status, offText)
            if (line != null) Text(line, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline) else content()
        }
    }
}

@Composable
private fun Item(text: String, trailing: String? = null, detail: String? = null, ref: HomeRef? = null, onOpen: (HomeRef?) -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(enabled = ref != null) { onOpen(ref) }.padding(vertical = 6.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(text, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
            trailing?.let { Text(it, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.outline) }
        }
        detail?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline) }
    }
}

@Composable
private fun Footer(label: String, ref: HomeRef, onOpen: (HomeRef?) -> Unit) = TextButton({ onOpen(ref) }) { Text(label) }

@Composable
private fun ScheduleCard(model: AppViewModel, view: HomeSnapshot, onOpen: (HomeRef?) -> Unit) {
    val s = view.schedule
    val stale = s?.status == "stale" || s?.feed?.freshness == "stale"
    SectionCard("Today's schedule", "schedule", s?.status, model, note = if (stale) "The calendar may be out of date: its last sync is old." else null) {
        if (s == null) return@SectionCard
        if (s.onLeave) Text("You are on leave today.", style = MaterialTheme.typography.titleSmall)
        for (e in s.allDay + s.events) Item(eventTitle(e), eventTime(e), e.location?.takeIf { it.isNotBlank() && !e.redacted }, e.ref, onOpen)
        if (s.status == "empty") Text(if (s.feedConfigured == false) "No calendar is connected. Add one in the web control panel under Settings > Accounts." else "Nothing on your calendar today.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
        s.nextEvent?.let { HorizontalDivider(); Text("Next: ${eventTitle(it)} · ${dayClock(it.start)}", style = MaterialTheme.typography.bodySmall) }
        Footer("Open calendar", HomeRef("calendar"), onOpen)
    }
}

private fun eventTitle(e: HomeEvent): String = e.title.ifBlank { "Busy" }

@Composable
private fun RemindersCard(model: AppViewModel, view: HomeSnapshot, onOpen: (HomeRef?) -> Unit) {
    val r = view.reminders
    SectionCard("Reminders", "reminders", r?.status, model) {
        if (r == null) return@SectionCard
        if (r.status == "empty") Text("No reminders due today or in the next ${r.upcomingDays} days.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
        ReminderGroup("Overdue", r.overdue, true, onOpen); ReminderGroup("Today", r.today, false, onOpen); ReminderGroup("Coming up", r.upcoming, false, onOpen)
        Footer("Open reminders", HomeRef("reminders"), onOpen)
    }
}

@Composable
private fun ReminderGroup(label: String, items: List<HomeReminder>, urgent: Boolean, onOpen: (HomeRef?) -> Unit) {
    if (items.isEmpty()) return
    Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = if (urgent) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.outline)
    for (x in items) Item(x.text, if (label == "Coming up") dayClock(x.dueAt) else clock(x.dueAt), null, x.ref, onOpen)
}

@Composable
private fun TasksCard(model: AppViewModel, view: HomeSnapshot, onOpen: (HomeRef?) -> Unit) {
    val t = view.tasks
    SectionCard("Open tasks", "tasks", t?.status, model) {
        if (t == null) return@SectionCard
        if (t.status == "empty") Text("No open tasks.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
        else {
            Text(plural(t.total, "open task") + (if (t.fromMeetings > 0) " · ${t.fromMeetings} from meetings" else "") + " · tasks have no due dates", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
            for (x in t.items) Item(x.text, null, x.origin?.let { if (it.kind == "meeting") "From meeting" + (it.meetingTitle?.let { m -> ": $m" } ?: "") else "From note" + (it.noteTitle?.let { n -> ": $n" } ?: "") }, x.ref, onOpen)
            if (t.total > t.shown) Text("and ${t.total - t.shown} more", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
        }
        Footer("Open to do", HomeRef("tasks"), onOpen)
    }
}

@Composable
private fun ReviewsCard(model: AppViewModel, view: HomeSnapshot, onOpen: (HomeRef?) -> Unit) {
    val v = view.reviews
    SectionCard("Waiting for your review", "reviews", v?.status, model, offText = "Note and meeting processing are turned off.", note = if (v?.status == "partial") "One of the review lists could not be read, so these counts may be incomplete." else null) {
        if (v == null) return@SectionCard
        Text("Suggestions written by the local model. Nothing here is a task, reminder or note until you accept it.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
        if (v.status == "empty") Text("No suggestions waiting.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
        v.noteProposals?.takeIf { it.status == "ok" }?.let { q ->
            Text(plural(q.count, "NOTE SUGGESTION"), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
            for (x in q.items) Item(x.text, null, x.noteTitle?.let { "From note: $it" }, x.ref, onOpen)
            if (q.count > q.items.size) Text("and ${q.count - q.items.size} more", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
        }
        v.meetingActions?.takeIf { it.status == "ok" }?.let { q ->
            Text(plural(q.count, "MEETING ACTION CANDIDATE"), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
            for (x in q.items) Item(x.text, null, listOfNotNull(x.meetingTitle?.let { "From meeting: $it" }, x.assignee).joinToString(" · ").ifBlank { null }, x.ref, onOpen)
            if (q.count > q.items.size) Text("and ${q.count - q.items.size} more", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
        }
    }
}

@Composable
private fun WeatherCard(model: AppViewModel, view: HomeSnapshot) {
    val w = view.weather
    SectionCard(
        "Weather" + (w?.location?.let { " · $it" } ?: ""), "weather", w?.status, model, offText = "Weather is turned off.",
        note = if (w?.status == "stale") "Out of date: last updated ${plural(((w.ageSeconds ?: 0) / 60).toInt().coerceAtLeast(1), "minute")} ago." else null,
    ) {
        if (w == null) return@SectionCard
        if (w.status == "not_configured") Text("Set your location in the web control panel under Settings > Assistant to see the weather.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
        else {
            for (line in weatherLines(w)) Text(line, style = MaterialTheme.typography.bodyMedium)
            Text("Observed ${w.observedAt?.let { clock(it) } ?: "—"} · Weather data by ${w.attribution?.name ?: "the provider"}${w.attribution?.license?.let { " ($it)" } ?: ""}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun QuickActions(view: HomeSnapshot, onOpen: (HomeRef?) -> Unit) {
    if (view.restricted || view.quickActions.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("Quick actions", style = MaterialTheme.typography.titleSmall, modifier = Modifier.semantics { heading() })
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (q in view.quickActions) AssistChip({ onOpen(q.ref) }, label = { Text(q.label) })
        }
    }
}

@Composable
private fun BriefCard(brief: HomeBrief, onOpen: (HomeRef?) -> Unit, onClose: () -> Unit) {
    Card(Modifier.fillMaxWidth().semantics { contentDescription = "Today's briefing" }, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.5f))) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Brief for today", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                OutlinedButton(onClose) { Text("Close") }
            }
            if (brief.mode == "generated" && !brief.narrative.isNullOrBlank()) Text(brief.narrative, style = MaterialTheme.typography.bodyMedium)
            Text(briefHeadline(brief), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
            if (brief.partial) Text("▲ Some sources could not be read, so this briefing may be incomplete.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary)
            if (brief.lines.isEmpty()) Text("Nothing to report for today.", style = MaterialTheme.typography.bodyMedium)
            for (line in brief.lines) Row(Modifier.fillMaxWidth().clickable(enabled = line.ref != null) { onOpen(line.ref) }.padding(vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(briefLabel(line.status), style = MaterialTheme.typography.labelSmall, color = if (line.status == "pending_review") MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.outline, modifier = Modifier.padding(top = 2.dp))
                Text(line.text, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}
