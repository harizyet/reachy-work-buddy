package app.reachy.companion.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.background
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel
import app.reachy.companion.data.MeetingLink
import app.reachy.companion.data.PROCESSING_STATE_LABEL
import app.reachy.companion.data.PROPOSAL_FROM_LABEL
import app.reachy.companion.data.PROPOSAL_KIND_LABEL
import app.reachy.companion.data.Proposal
import app.reachy.companion.data.processingFailure
import app.reachy.companion.data.reminderWhen
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZoneOffset

/**
 * Everything below a note's text, as on the web: send the saved note to Reachy, see where it is, review what Reachy found, and tie the note to a recorded meeting.
 * Reachy's findings are suggestions until accepted and say where their evidence came from. Shown only when the hub has Notepad processing on. All text is drawn as text.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ProcessingSection(model: AppViewModel, noteId: String?, modifier: Modifier = Modifier, onSend: (force: Boolean, includeMeetings: Boolean) -> Unit) {
    LaunchedEffect(noteId) { if (noteId != null) model.openProcessing(noteId) }
    DisposableEffect(noteId) { onDispose { model.closeProcessing() } }
    val data = noteId?.let { model.processing[it] }
    val links = noteId?.let { model.meetingLinks[it] }.orEmpty()
    val state = data?.state ?: "not_processed"
    val confirmed = links.filter { it.confirmed }
    var withMeetings by remember { mutableStateOf(false) }
    val busy = model.processingBusy || data?.inProgress == true
    val open = data?.proposals.orEmpty().filter { it.open }
    val added = data?.proposals.orEmpty().filter { it.status == "accepted" }
    val info = data?.proposals.orEmpty().filter { it.status == "noted" }
    var showInfo by remember { mutableStateOf(false) }
    val problem = MaterialTheme.colorScheme.error
    val muted = MaterialTheme.colorScheme.outline

    Column(modifier.fillMaxWidth().heightIn(max = 320.dp).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp)) {
        HorizontalDivider(Modifier.padding(bottom = 8.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.Center) {
            Text(
                PROCESSING_STATE_LABEL[state] ?: state, style = MaterialTheme.typography.labelMedium, color = muted,
                modifier = Modifier.padding(top = 12.dp).background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(50)).padding(horizontal = 10.dp, vertical = 4.dp),
            )
            if (state == "review_required" || state == "completed") {
                TextButton({ onSend(true, withMeetings) }, enabled = !busy) { Text("Process again", color = Accent) }
            } else {
                Button({ onSend(false, withMeetings) }, enabled = !busy) { Text(if (busy) "Working…" else "Send to Reachy") }
            }
            if (state == "failed" && data?.job != null && noteId != null) {
                Text(processingFailure(data.job.error), color = problem, modifier = Modifier.padding(top = 12.dp))
                TextButton({ model.retryProcessing(noteId, data.job.id) }) { Text("Retry", color = Accent) }
            }
        }
        if (confirmed.isNotEmpty()) {
            Row(Modifier.fillMaxWidth().clickable { withMeetings = !withMeetings }, verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Checkbox(withMeetings, { withMeetings = it })
                Text("Also use the linked meeting transcript" + if (confirmed.size > 1) "s" else "")
            }
        }
        model.processingMessage?.let { Text(it, color = problem, modifier = Modifier.padding(top = 4.dp)) }
        if (data?.noteChangedSinceJob == true && state != "not_processed") {
            Text("This note changed after it was last processed. The suggestions below come from the earlier text.", color = muted, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
        }
        data?.job?.meetings.orEmpty().filter { !it.included }.forEach {
            Text("The transcript of “${it.title}” was not used: ${it.reason ?: "unavailable"}. Process again once it is ready.", color = muted, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
        }

        if (open.isNotEmpty() && noteId != null) {
            Text("Suggestions from Reachy", fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 12.dp))
            Text("Not yet confirmed. Nothing is added to your tasks or reminders until you accept it.", color = muted, style = MaterialTheme.typography.bodySmall)
            open.forEach { ProposalCard(it, busy = it.status == "accepting", onAccept = { text, kind, due -> model.acceptProposal(noteId, it.id, text, kind, due) }, onDismiss = { model.dismissProposal(noteId, it.id) }) }
        }
        if (added.isNotEmpty()) {
            Text(
                "Added from this note: " + added.joinToString("; ") { if (it.recordId != null) "${PROPOSAL_KIND_LABEL[it.kind] ?: it.kind} “${it.text}”" else "“${it.text}” (reviewed)" } + ".",
                color = muted, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp),
            )
        }
        if (info.isNotEmpty()) {
            Text("Information that stays in the note (${info.size})" + if (showInfo) " ▾" else " ▸", color = Accent, modifier = Modifier.clickable { showInfo = !showInfo }.padding(top = 8.dp))
            if (showInfo) info.forEach { Text("• ${it.text}", style = MaterialTheme.typography.bodySmall) }
        }
        if (noteId != null) MeetingLinksBlock(model, noteId, links)
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun ProposalCard(p: Proposal, busy: Boolean, onAccept: (String?, String?, String?) -> Unit, onDismiss: () -> Unit) {
    var editing by remember { mutableStateOf(false) }
    var text by remember { mutableStateOf(p.text) }
    var kind by remember { mutableStateOf(if (p.kind == "reference") "task" else p.kind) }
    var due by remember { mutableStateOf<LocalDateTime?>(p.dueAt?.let { runCatching { OffsetDateTime.parse(it).atZoneSameInstant(ZoneId.systemDefault()).toLocalDateTime() }.getOrNull() }) }
    var pickDate by remember { mutableStateOf(false) }
    var pickTime by remember { mutableStateOf(false) }
    val effectiveKind = if (editing) kind else p.kind
    val needsTime = effectiveKind == "reminder" && (if (editing) due == null else p.dueAt == null)
    val muted = MaterialTheme.colorScheme.outline
    Column(Modifier.fillMaxWidth().padding(top = 8.dp).background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f), RoundedCornerShape(12.dp)).padding(12.dp)) {
        Text(PROPOSAL_KIND_LABEL[p.kind] ?: p.kind, style = MaterialTheme.typography.labelSmall, color = muted)
        Text(p.text, fontWeight = FontWeight.SemiBold)
        if (p.kind == "reminder" && p.dueAt != null) Text(reminderWhen(p.dueAt), color = muted, style = MaterialTheme.typography.bodySmall)
        p.sources.forEach {
            Text("“${it.quote}”", color = muted, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
            Text(if (it.kind == "note") "Your note" else "Meeting “${it.title ?: "meeting"}”" + (it.speaker?.let { s -> ", $s" } ?: ""), color = muted, style = MaterialTheme.typography.labelSmall)
        }
        Text(PROPOSAL_FROM_LABEL[p.evidenceFrom] ?: p.evidenceFrom, color = muted, style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(top = 4.dp))
        if (p.sourceChanged) Text("The note has changed since this was found.", color = muted, style = MaterialTheme.typography.labelSmall)
        p.ambiguity.forEach { Text("• $it", style = MaterialTheme.typography.bodySmall) }
        if (editing) {
            OutlinedTextField(text, { text = it.take(300) }, Modifier.fillMaxWidth().padding(top = 8.dp), label = { Text("Proposed text") })
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 4.dp)) {
                listOf("task" to "Task", "reminder" to "Reminder", "event" to "Review only").forEach { (value, label) ->
                    FilterChip(kind == value, { kind = value }, { Text(label) })
                }
            }
            if (kind == "reminder") {
                TextButton({ pickDate = true }) { Text(due?.let { reminderWhen(it.atZone(ZoneId.systemDefault()).toOffsetDateTime().toString()) } ?: "Choose a date and time", color = Accent) }
            }
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            TextButton(
                {
                    if (!editing) onAccept(null, null, null)
                    else onAccept(text.trim(), kind, if (kind == "reminder") due?.atZone(ZoneId.systemDefault())?.toOffsetDateTime()?.toString() else null)
                },
                enabled = !busy && !needsTime && !(editing && text.isBlank()),
            ) { Text(if (editing) "Save and accept" else "Accept", color = Accent, fontWeight = FontWeight.Bold) }
            if (!editing) TextButton({ editing = true }) { Text("Edit and accept", color = Accent) }
            TextButton(onDismiss, enabled = !busy) { Text("Dismiss", color = Accent) }
        }
        if (needsTime) Text("Choose a time (Edit and accept) to add it as a reminder.", color = muted, style = MaterialTheme.typography.labelSmall)
    }
    if (pickDate) {
        val start = (due ?: LocalDateTime.now().plusHours(1).withMinute(0).withSecond(0).withNano(0)).toLocalDate()
        val state = rememberDatePickerState(initialSelectedDateMillis = start.atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli())
        DatePickerDialog(
            { pickDate = false },
            confirmButton = {
                TextButton({
                    state.selectedDateMillis?.let { ms ->
                        val date = java.time.Instant.ofEpochMilli(ms).atZone(ZoneOffset.UTC).toLocalDate()
                        due = LocalDateTime.of(date, due?.toLocalTime() ?: LocalTime.of(LocalTime.now().plusHours(1).hour, 0))
                    }
                    pickDate = false; pickTime = true
                }) { Text("Next") }
            },
            dismissButton = { TextButton({ pickDate = false }) { Text("Cancel") } },
        ) { DatePicker(state) }
    }
    if (pickTime) {
        val at = due ?: LocalDateTime.now().plusHours(1).withMinute(0)
        val state = rememberTimePickerState(initialHour = at.hour, initialMinute = at.minute)
        AlertDialog(
            { pickTime = false }, text = { TimePicker(state) },
            confirmButton = { TextButton({ due = LocalDateTime.of((due ?: at).toLocalDate(), LocalTime.of(state.hour, state.minute)); pickTime = false }) { Text("OK") } },
            dismissButton = { TextButton({ pickTime = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun MeetingLinksBlock(model: AppViewModel, noteId: String, links: List<MeetingLink>) {
    var picking by remember { mutableStateOf(false) }
    val muted = MaterialTheme.colorScheme.outline
    val linked = links.filter { it.confirmed }.map { it.meetingId }.toSet()
    if (links.isNotEmpty()) Text("Meetings", fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 12.dp))
    links.forEach { link ->
        Column(Modifier.padding(top = 4.dp)) {
            val title = link.meeting?.title ?: "a meeting that was deleted"
            val when_ = link.meeting?.startedAt?.let { " (" + reminderWhen(it) + ")" }.orEmpty()
            val notReady = if (link.meeting != null && !link.meeting.transcriptReady) " · transcript not ready" else ""
            Text((if (link.confirmed) "Linked to " else "Taken during this meeting? ") + title + when_ + notReady, color = if (link.confirmed) MaterialTheme.colorScheme.onSurface else muted)
            Row {
                if (!link.confirmed) TextButton({ model.setMeetingLink(noteId, link.meetingId, true) }) { Text("Link", color = Accent) }
                TextButton({ model.setMeetingLink(noteId, link.meetingId, false) }) { Text(if (link.confirmed) "Unlink" else "Not this meeting", color = Accent) }
            }
        }
    }
    TextButton({ if (model.meetings.isEmpty()) model.loadMeetings(); picking = true }) { Text("Link to a meeting…", color = Accent) }
    DropdownMenu(picking, { picking = false }) {
        val choices = model.meetings.filter { it.id !in linked }
        if (choices.isEmpty()) DropdownMenuItem({ Text("No meetings to link") }, { picking = false }, enabled = false)
        choices.forEach { m -> DropdownMenuItem({ Text(m.title) }, { picking = false; model.setMeetingLink(noteId, m.id, true) }) }
    }
}
