package app.reachy.companion.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.FilterChip
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.AssistChip
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Delete
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.TextButton
import app.reachy.companion.data.countOccurrences
import app.reachy.companion.data.lineAt
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Slider
import app.reachy.companion.data.segmentText
import app.reachy.companion.data.speakerDisplayName
import app.reachy.companion.data.speakerAt
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.FiberManualRecord
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.DisposableEffect
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import app.reachy.companion.AppViewModel
import app.reachy.companion.DeepReviewController
import app.reachy.companion.RecordingController
import app.reachy.companion.data.DeepReviewInfo
import app.reachy.companion.data.Meeting
import kotlinx.coroutines.delay

fun statusLabel(status: String) = when (status) {
    "uploaded" -> "Uploaded"
    "preprocessing" -> "Preparing audio"
    "transcribing" -> "Transcribing"
    "diarizing" -> "Identifying speakers"
    // "aligning" is where every meeting rests once transcription and speaker detection are done (combining them is not
    // implemented), so it is a finished meeting, not one still working.
    "aligning", "complete" -> "Ready"
    "analyzing" -> "Finishing up"
    "failed" -> "Failed"
    "cancelled" -> "Cancelled"
    else -> status
}

fun clock(seconds: Double): String = "%d:%02d".format(seconds.toInt() / 60, seconds.toInt() % 60)

@Composable
fun MeetingsScreen(model: AppViewModel, modifier: Modifier = Modifier, onUseAsContext: () -> Unit = {}) {
    val open = model.openMeeting
    BackHandler(open != null) { model.showMeeting(null) }
    if (open != null) MeetingDetail(model, open, modifier, onUseAsContext) else MeetingList(model, modifier)
}

@Composable
private fun MeetingList(model: AppViewModel, modifier: Modifier) {
    val context = LocalContext.current
    val recording = model.recording
    var elapsed by remember { mutableLongStateOf(0) }
    var error by remember { mutableStateOf<String?>(null) }
    var glossary by remember { mutableStateOf(false) }
    var pendingDelete by remember { mutableStateOf<Meeting?>(null) }
    var confirmClear by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { model.retryPendingUploads() }
    LaunchedEffect(RecordingController.uploadedCount) { model.loadMeetings() }
    LaunchedEffect(recording) {
        // Derived from the start time, so the timer is right after returning to this tab.
        while (recording) { elapsed = (System.currentTimeMillis() - model.recordingStartedAt) / 1000; delay(500) }
    }

    fun begin() { error = null; model.startRecording() }
    // Android 13+ hides the "recording" notification unless allowed; recording still works if declined.
    val notifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { begin() }
    fun beginWithNotifications() {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        else begin()
    }
    fun finish() = model.stopRecording()
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { if (it) beginWithNotifications() else error = "Microphone permission is needed to record" }

    if (glossary) GlossaryDialog(model) { glossary = false }
    pendingDelete?.let { meeting ->
        ConfirmDeleteDialog(meeting.title, onDismiss = { pendingDelete = null }, onConfirm = { model.deleteMeeting(meeting.id); pendingDelete = null })
    }
    if (confirmClear) AlertDialog(
        onDismissRequest = { confirmClear = false },
        title = { Text("Delete failed and cancelled meetings?") },
        text = { Text("This removes every failed or cancelled meeting and its recording. It cannot be undone.") },
        confirmButton = { TextButton({ model.clearFailedMeetings(); confirmClear = false }) { Text("Delete") } },
        dismissButton = { TextButton({ confirmClear = false }) { Text("Cancel") } },
    )
    Column(modifier.fillMaxSize()) {
        Column(Modifier.fillMaxWidth().padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Button(
                {
                    if (recording) finish()
                    else if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) beginWithNotifications()
                    else permission.launch(Manifest.permission.RECORD_AUDIO)
                },
                enabled = !model.uploading,
                colors = if (recording) ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.tertiary) else ButtonDefaults.buttonColors(),
            ) {
                Icon(if (recording) Icons.Default.Stop else Icons.Default.FiberManualRecord, null)
                Text(
                    when {
                        model.uploading -> "  Uploading…"
                        recording -> "  Stop and save  ${clock(elapsed.toDouble())}"
                        else -> "  Record a meeting"
                    },
                )
            }
            if (recording) Text("Recording continues if you lock the phone or switch apps.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
        }
        TextButton({ glossary = true }, contentPadding = PaddingValues(horizontal = 16.dp)) { Text("My terms (names and products Reachy should recognise)") }
        ErrorLine(error ?: model.recordError ?: model.listError)
        if (model.meetings.isEmpty()) Text("No meetings yet.", Modifier.padding(16.dp))
        val failedCount = model.meetings.count { it.status == "failed" || it.status == "cancelled" }
        if (failedCount > 0) TextButton({ confirmClear = true }, contentPadding = PaddingValues(horizontal = 16.dp)) {
            Text("Delete failed and cancelled ($failedCount)")
        }
        LazyColumn {
            items(model.meetings, key = { it.id }) { meeting ->
                Row(Modifier.fillMaxWidth().clickable { model.showMeeting(meeting.id) }.padding(start = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f).padding(vertical = 14.dp)) {
                        Text(meeting.title, style = MaterialTheme.typography.titleMedium)
                        Text(statusLabel(meeting.status), style = MaterialTheme.typography.bodySmall)
                    }
                    if (meeting.status in IN_PROGRESS) TextButton({ model.cancelMeeting(meeting.id) }) { Text("Cancel") }
                    else IconButton({ pendingDelete = meeting }) { Icon(Icons.Default.Delete, "Delete ${meeting.title}") }
                }
                HorizontalDivider()
            }
        }
    }
}

@Composable
private fun MeetingDetail(model: AppViewModel, meeting: Meeting, modifier: Modifier, onUseAsContext: () -> Unit) {
    val context = LocalContext.current
    var renaming by remember { mutableStateOf<String?>(null) }
    var editing by remember { mutableStateOf<Int?>(null) }
    var replacing by remember { mutableStateOf(false) }
    var choosingModel by remember { mutableStateOf(false) }
    var warningDeep by remember { mutableStateOf(false) }
    var editingTerms by remember { mutableStateOf(false) }
    var section by remember { mutableStateOf("transcript") }
    var menu by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    var rerunKind by remember { mutableStateOf<String?>(null) }
    val segments = meeting.transcript.orEmpty()
    val ready = segments.isNotEmpty() && meeting.status in READY
    Column(modifier.fillMaxSize()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton({ model.showMeeting(null) }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back to meetings") }
            Column(Modifier.weight(1f)) {
                Text(meeting.title, style = MaterialTheme.typography.titleMedium)
                Text(statusLabel(meeting.status), style = MaterialTheme.typography.bodySmall)
            }
            if (section == "transcript" && segments.isNotEmpty()) {
                TextButton({ replacing = true }) { Text("Replace") }
                TextButton({ rerunKind = null; model.loadDeepInfo(); choosingModel = true }, enabled = !model.suggesting && !DeepReviewController.reachyUnavailable) {
                    Text(if (model.suggesting) "Checking…" else "Suggest")
                }
            }
            Box {
                IconButton({ menu = true }) { Icon(Icons.Default.MoreVert, "Meeting options") }
                DropdownMenu(menu, { menu = false }) {
                    DropdownMenuItem({ Text("Delete meeting") }, { menu = false; confirmDelete = true })
                }
            }
        }
        ErrorLine(meeting.errorDetail ?: model.listError)
        if (ready) {
            Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(section == "summary", { section = "summary"; if (meeting.summary == null && model.generatingKind == null) model.generateOutput("summary", "local") }, { Text("Summary") })
                FilterChip(section == "minutes", { section = "minutes"; if (meeting.minutes == null && model.generatingKind == null) model.generateOutput("minutes", "local") }, { Text("Minutes") })
                FilterChip(section == "transcript", { section = "transcript" }, { Text("Transcript") })
                AssistChip({ model.useAsContext(meeting); onUseAsContext() }, { Text("Use as context") })
            }
        }
        if (section != "transcript") {
            OutputPanel(model, meeting, section) { kind -> rerunKind = kind; model.loadDeepInfo(); choosingModel = true }
            return@Column
        }
        if (segments.isNotEmpty()) {
            TextButton({ editingTerms = true }, contentPadding = PaddingValues(horizontal = 16.dp)) {
                Text(
                    if (meeting.keyTerms.isEmpty()) "Add key terms (names, products)" else "Key terms: " + meeting.keyTerms.joinToString(", "),
                    style = MaterialTheme.typography.labelLarge, maxLines = 2,
                )
            }
        }
        model.suggestionNote?.let { Text(it, Modifier.padding(horizontal = 16.dp), style = MaterialTheme.typography.bodySmall) }
        if (segments.isEmpty()) Text("No transcript yet.", Modifier.padding(16.dp))
        val player = model.player
        val loaded = player.meetingId == meeting.id
        LaunchedEffect(player.playing, loaded) {
            while (loaded && player.playing) { player.refresh(); kotlinx.coroutines.delay(250) }
        }
        DisposableEffect(meeting.id) { onDispose { if (player.meetingId == meeting.id) player.release() } }
        if (segments.isNotEmpty()) {
            Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton({ if (loaded) player.toggle() else model.playMeetingFrom(meeting.id, 0.0) }, enabled = !player.loading) {
                    Icon(if (loaded && player.playing) Icons.Default.Pause else Icons.Default.PlayArrow, if (loaded && player.playing) "Pause recording" else "Play recording")
                }
                if (loaded && player.durationMs > 0) {
                    Slider(
                        value = player.positionMs.toFloat(), onValueChange = { player.seekTo(it.toInt()) },
                        valueRange = 0f..player.durationMs.toFloat(), modifier = Modifier.weight(1f),
                    )
                    Text("${clock(player.positionMs / 1000.0)} / ${clock(player.durationMs / 1000.0)}", style = MaterialTheme.typography.labelSmall)
                } else Text(
                    if (player.loading) "Loading the recording…" else "Play the recording; tap a line to start from it.",
                    Modifier.weight(1f), style = MaterialTheme.typography.bodySmall,
                )
            }
            ErrorLine(player.error)
        }
        val playingLine = if (loaded) lineAt(segments, player.positionMs / 1000.0) else null
        LazyColumn(Modifier.padding(horizontal = 16.dp)) {
            val groups = model.suggestions.distinctBy { it.original to it.suggested }
            if (groups.isNotEmpty()) item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Suggested corrections", Modifier.weight(1f), style = MaterialTheme.typography.titleSmall)
                    TextButton({ groups.forEach(model::changeAll) }) { Text("Change all") }
                }
            }
            items(groups) { suggestion ->
                val places = countOccurrences(meeting, suggestion.original)
                Card(Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                    Column(Modifier.padding(12.dp)) {
                        Text("${suggestion.original}  →  ${suggestion.suggested}", style = MaterialTheme.typography.titleSmall)
                        Text(
                            when (suggestion.confidence) {
                                "high" -> "High confidence · same letters as your term"
                                "likely" -> "Matches your term · judged by the model, check it"
                                else -> "Model guess · check before applying"
                            },
                            style = MaterialTheme.typography.labelSmall,
                            color = if (suggestion.confidence == "high") MaterialTheme.colorScheme.secondary else MaterialTheme.colorScheme.outline,
                        )
                        if (suggestion.reason.isNotBlank()) Text(suggestion.reason, style = MaterialTheme.typography.bodySmall)
                        Text("Appears in $places place${if (places == 1) "" else "s"}", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
                        Row {
                            TextButton({ model.changeAll(suggestion) }, enabled = places > 0) { Text(if (places > 1) "Change all $places" else "Change") }
                            TextButton({ model.dismissSuggestion(suggestion) }) { Text("Dismiss") }
                        }
                    }
                }
            }
            itemsIndexed(segments) { index, segment ->
                val label = speakerAt(meeting, index, segment)
                val previous = segments.getOrNull(index - 1)?.let { speakerAt(meeting, index - 1, it) }
                if (label != null && (index == 0 || label != previous)) {
                    TextButton({ renaming = label }, contentPadding = PaddingValues(0.dp)) {
                        Text("${speakerDisplayName(meeting, label)}  ·  ${clock(segment.start)}", style = MaterialTheme.typography.labelLarge)
                    }
                } else if (label == null) {
                    Text(clock(segment.start), style = MaterialTheme.typography.labelSmall)
                }
                Text(
                    segmentText(meeting, index),
                    Modifier.clickable { model.playMeetingFrom(meeting.id, segment.start) },
                    fontWeight = if (playingLine == index) androidx.compose.ui.text.font.FontWeight.Bold else null,
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton({ editing = index }, contentPadding = PaddingValues(0.dp)) { Text("Edit", style = MaterialTheme.typography.labelSmall) }
                    if (meeting.corrections.containsKey(index.toString())) {
                        Text("  edited", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.secondary)
                    }
                }
                Spacer(Modifier.height(4.dp))
            }
        }
    }
    fun startDeep() {
        val kind = rerunKind
        rerunKind = null
        if (kind != null) model.startDeepOutput(kind) else model.startDeepReview()
    }
    if (choosingModel) ModelChoiceDialog(
        title = if (rerunKind == null) "Check with which model?" else "Write the $rerunKind with which model?",
        info = model.deepInfo,
        onDismiss = { choosingModel = false; rerunKind = null },
        onChoose = { choice ->
            choosingModel = false
            val kind = rerunKind
            when {
                choice == "deep" -> warningDeep = true
                kind != null -> { rerunKind = null; model.generateOutput(kind, choice) }
                else -> model.suggestCorrections(choice)
            }
        },
    )
    if (confirmDelete) ConfirmDeleteDialog(meeting.title, onDismiss = { confirmDelete = false }, onConfirm = { confirmDelete = false; model.deleteMeeting(meeting.id) })
    val notifyPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { startDeep() }
    if (warningDeep) DeepWarningDialog(
        info = model.deepInfo,
        onDismiss = { warningDeep = false; rerunKind = null },
        onConfirm = {
            warningDeep = false
            // Android 13+ hides the "Reachy is available again" notification unless allowed; the job runs either way.
            if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                notifyPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
            } else startDeep()
        },
    )
    LaunchedEffect(DeepReviewController.job?.result, DeepReviewController.job?.id) { model.acceptDeepResult(DeepReviewController.job) }
    if (editingTerms) TextDialog(
        title = "Key terms for this meeting", label = "Names and terms, separated by commas", initial = meeting.keyTerms.joinToString(", "),
        confirm = "Save", multiline = true, allowBlank = true, onDismiss = { editingTerms = false },
        onConfirm = { text -> model.setKeyTerms(text.split(",", "\n").map { it.trim() }.filter { it.isNotEmpty() }); editingTerms = false },
    )
    if (replacing) ReplaceDialog(onDismiss = { replacing = false }, onConfirm = { find, replace -> model.replaceEverywhere(find, replace); replacing = false })
    renaming?.let { label ->
        TextDialog(
            title = "Who is ${speakerDisplayName(meeting, label)}?", label = "Name", initial = meeting.speakerNames[label].orEmpty(),
            confirm = "Save", onDismiss = { renaming = null }, onConfirm = { model.renameSpeaker(label, it); renaming = null },
            extra = if (meeting.speakerNames.containsKey(label)) "Clear name" to { model.renameSpeaker(label, ""); renaming = null } else null,
            allowBlank = false,
        )
    }
    editing?.let { index ->
        TextDialog(
            title = "Edit text", label = "Transcript", initial = segmentText(meeting, index), confirm = "Save", multiline = true,
            onDismiss = { editing = null }, onConfirm = { model.editSegment(index, it); editing = null },
            extra = if (meeting.corrections.containsKey(index.toString())) "Restore original" to { model.restoreSegment(index); editing = null } else null,
        )
    }
}

@Composable
private fun TextDialog(
    title: String, label: String, initial: String, confirm: String, onDismiss: () -> Unit, onConfirm: (String) -> Unit,
    multiline: Boolean = false, allowBlank: Boolean = false, extra: Pair<String, () -> Unit>? = null,
) {
    var text by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { OutlinedTextField(text, { text = it }, label = { Text(label) }, singleLine = !multiline, minLines = if (multiline) 3 else 1) },
        confirmButton = { TextButton({ onConfirm(text) }, enabled = allowBlank || text.isNotBlank()) { Text(confirm) } },
        dismissButton = {
            Row {
                extra?.let { (name, action) -> TextButton(action) { Text(name) } }
                TextButton(onDismiss) { Text("Cancel") }
            }
        },
    )
}

@Composable
private fun ReplaceDialog(onDismiss: () -> Unit, onConfirm: (String, String) -> Unit) {
    var find by remember { mutableStateOf("") }
    var replace by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Change everywhere") },
        text = {
            Column {
                OutlinedTextField(find, { find = it }, label = { Text("Change") }, singleLine = true)
                OutlinedTextField(replace, { replace = it }, label = { Text("To") }, singleLine = true, modifier = Modifier.padding(top = 8.dp))
                Text("Whole words, ignoring capitals. You can restore any line afterwards.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
            }
        },
        confirmButton = { TextButton({ onConfirm(find, replace) }, enabled = find.isNotBlank() && replace.isNotBlank()) { Text("Change all") } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun ModelChoiceDialog(title: String, info: DeepReviewInfo?, onDismiss: () -> Unit, onChoose: (String) -> Unit) {
    val deepOk = info?.available == true
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                Text("Local: runs on your homelab. The transcript stays private. Quick.", style = MaterialTheme.typography.bodyMedium)
                Text(
                    "Deep local: a larger model on your homelab, still private and more accurate. Reachy is unavailable for about ${((info?.etaSeconds ?: 330) / 60.0).let { Math.round(it).coerceAtLeast(1) }} minutes while it runs.",
                    style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp),
                )
                if (info != null && !deepOk) {
                    Text("Deep local is unavailable: ${info.reason ?: "not ready"}.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(top = 4.dp))
                }
                Text("Cloud: sends the transcript text to your cloud provider. Usually more accurate than local.", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp))
            }
        },
        confirmButton = { TextButton({ onChoose("local") }) { Text("Local") } },
        dismissButton = {
            Row {
                TextButton({ onChoose("deep") }, enabled = deepOk) { Text("Deep local") }
                TextButton({ onChoose("cloud") }) { Text("Cloud") }
                TextButton(onDismiss) { Text("Cancel") }
            }
        },
    )
}

@Composable
private fun DeepWarningDialog(info: DeepReviewInfo?, onDismiss: () -> Unit, onConfirm: () -> Unit) {
    val minutes = Math.round((info?.etaSeconds ?: 330) / 60.0).coerceAtLeast(1)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Reachy will be unavailable") },
        text = {
            Text(
                "The larger model takes over the GPU for about $minutes minutes: it loads (about 2 minutes), reviews this meeting, " +
                    "then Reachy's standard model reloads (about 1.5 minutes). Reachy's local replies will not work until then. " +
                    "You will get a notification here and a Telegram message when Reachy is back online.",
            )
        },
        confirmButton = { TextButton(onConfirm) { Text("Start deep review") } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun GlossaryDialog(model: AppViewModel, onClose: () -> Unit) {
    var draft by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { model.loadGlossary() }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("My terms") },
        text = {
            Column {
                Text("Names, products and jargon. Suggestions match transcript words against these.", style = MaterialTheme.typography.bodySmall)
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 8.dp)) {
                    OutlinedTextField(draft, { draft = it }, Modifier.weight(1f), label = { Text("Add a term") }, singleLine = true)
                    TextButton({ model.addGlossaryTerm(draft); draft = "" }, enabled = draft.isNotBlank()) { Text("Add") }
                }
                LazyColumn(Modifier.heightIn(max = 280.dp)) {
                    items(model.glossary.toList()) { term ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(term, Modifier.weight(1f).padding(vertical = 8.dp))
                            TextButton({ model.deleteGlossaryTerm(term) }) { Text("Remove") }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClose) { Text("Done") } },
    )
}

private val IN_PROGRESS = setOf("uploaded", "preprocessing", "transcribing", "diarizing", "analyzing")
private val READY = setOf("aligning", "analyzing", "complete")

@Composable
private fun ConfirmDeleteDialog(title: String, onDismiss: () -> Unit, onConfirm: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Delete this meeting?") },
        text = { Text("“$title” will be removed with its recording, transcript, speaker names, corrections, summary and minutes. This cannot be undone.") },
        confirmButton = { TextButton(onConfirm) { Text("Delete") } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun OutputPanel(model: AppViewModel, meeting: Meeting, kind: String, onRerun: (String) -> Unit) {
    val output = if (kind == "summary") meeting.summary else meeting.minutes
    val name = if (kind == "summary") "summary" else "minutes"
    Column(Modifier.padding(16.dp).verticalScroll(rememberScrollState())) {
        when {
            model.generatingKind == kind -> Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(Modifier.size(24.dp))
                Text("  Writing the $name with the local model…")
            }
            output == null -> {
                Text("No $name yet.")
                Button({ model.generateOutput(kind, "local") }, Modifier.padding(top = 8.dp)) { Text("Write the $name (local model)") }
            }
            else -> {
                SelectionContainer { Text(output.text) }
                Text(
                    when (output.tier) {
                        "deep" -> "Written by the larger local model"
                        "cloud" -> "Written by the cloud model"
                        else -> "Written by the local model"
                    } + if (output.generatedAt.length >= 16) " · ${output.generatedAt.take(16).replace('T', ' ')}" else "",
                    style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(top = 12.dp),
                )
                Text("A model wrote this from a speech-to-text transcript, so check it. If it is not accurate enough, rerun it on a stronger model.", style = MaterialTheme.typography.bodySmall)
                Row {
                    TextButton({ onRerun(kind) }, enabled = !DeepReviewController.reachyUnavailable) { Text("Rerun with another model…") }
                    TextButton({ model.clearOutput(kind) }) { Text("Clear") }
                }
            }
        }
    }
}
