package app.reachy.companion.ui

import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel
import app.reachy.companion.RecordingController
import app.reachy.companion.data.RecordingGate
import app.reachy.companion.data.ReminderIssue
import app.reachy.companion.data.classLabel
import app.reachy.companion.data.recordingTitle
import app.reachy.companion.data.reminderNote
import app.reachy.companion.data.scheduleTitle
import app.reachy.companion.data.scheduleWhen
import app.reachy.companion.data.scheduledText

/**
 * The meeting a reminder prepared. Starting is always the owner's tap on Record: the microphone is never started by a notification. A second tap, or a recording that already
 * exists for this occurrence, offers to open that meeting instead of making another.
 */
@Composable
fun PreparedMeetingCard(model: AppViewModel, onRecord: () -> Unit, onOpen: (String) -> Unit) {
    val prepared = model.prepared ?: return
    // Re-read whenever a recording starts, stops or uploads.
    LaunchedEffect(model.recording, RecordingController.uploadedCount) { }
    val gate = model.preparedGate() ?: return
    Card(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Meeting reminder", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
            Text(recordingTitle(prepared), style = MaterialTheme.typography.titleMedium)
            Text(scheduledText(prepared.startMs), style = MaterialTheme.typography.bodySmall)
            when (gate) {
                RecordingGate.Ready -> {
                    Text("Nothing is recorded until you tap Record.", style = MaterialTheme.typography.bodySmall)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onRecord) { Text("Record this meeting") }
                        TextButton({ model.clearPrepared() }) { Text("Not now") }
                    }
                }
                RecordingGate.RecordingThis -> Text("Recording this meeting now.", style = MaterialTheme.typography.bodyMedium)
                RecordingGate.RecordingSomethingElse -> {
                    Text("A recording is already running. Stop it first if this is a different meeting.", style = MaterialTheme.typography.bodyMedium)
                    TextButton({ model.clearPrepared() }) { Text("Dismiss") }
                }
                RecordingGate.WaitingToUpload -> {
                    Text("A recording of this meeting is on this phone and will upload when the hub is reachable.", style = MaterialTheme.typography.bodyMedium)
                    TextButton({ model.clearPrepared() }) { Text("Dismiss") }
                }
                is RecordingGate.AlreadyRecorded -> {
                    Text("This meeting was already recorded.", style = MaterialTheme.typography.bodyMedium)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton({ onOpen(gate.meetingId); model.clearPrepared() }) { Text("Open the recording") }
                        TextButton({ model.clearPrepared() }) { Text("Dismiss") }
                    }
                }
            }
        }
    }
}

/** Why reminders may not arrive, and the next few days of the calendar with the classification the hub gave each event. */
@Composable
fun UpcomingSchedule(model: AppViewModel) {
    val context = LocalContext.current
    if (!model.prefs.meetingReminders && model.schedule.isEmpty()) return
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
        Text("Calendar, next 3 days", style = MaterialTheme.typography.titleSmall)
        for (issue in model.reminderIssues) {
            Text(issue.text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary, modifier = Modifier.padding(top = 2.dp))
            if (issue == ReminderIssue.NotificationsBlocked || issue == ReminderIssue.ChannelBlocked) {
                TextButton({ context.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }) { Text("Notification settings") }
            }
        }
        model.scheduleError?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary) }
        if (model.schedule.isEmpty() && model.scheduleError == null && model.prefs.meetingReminders) Text("Nothing on the calendar feed in the next 3 days.", style = MaterialTheme.typography.bodySmall)
        for (item in model.schedule) {
            Column(Modifier.padding(vertical = 4.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(classLabel(item), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                    Text(scheduleTitle(item), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f, fill = false))
                }
                Text(listOfNotNull(scheduleWhen(item), reminderNote(item)).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
            }
        }
    }
}
