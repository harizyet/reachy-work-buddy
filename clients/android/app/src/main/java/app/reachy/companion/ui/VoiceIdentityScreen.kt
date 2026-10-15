package app.reachy.companion.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import app.reachy.companion.AppViewModel
import app.reachy.companion.PcmCapture
import app.reachy.companion.data.ENROLLMENT_PHRASES
import app.reachy.companion.data.draftProgress
import app.reachy.companion.data.reasonText

/** One-utterance recorder for the enrolment, test and evaluation screens: the same in-memory capture voice chat uses. */
class ClipRecorder {
    var recording by mutableStateOf(false)
    var level by mutableStateOf(0f)
    var error by mutableStateOf<String?>(null)
    internal var start: () -> Unit = {}
    internal var stop: () -> Unit = {}
    fun begin() = start()
    fun cancel() = stop()
}

@Composable
fun rememberClipRecorder(model: AppViewModel, onClip: (ByteArray) -> Unit): ClipRecorder {
    val context = LocalContext.current
    val state = remember { ClipRecorder() }
    var got by remember { mutableStateOf(false) }
    val latest by androidx.compose.runtime.rememberUpdatedState(onClip)
    val capture = remember {
        PcmCapture(
            onLevel = { state.level = it },
            onUtterance = { got = true; latest(it) },
            onEnd = { error ->
                state.recording = false; state.level = 0f
                state.error = error ?: if (!got) "I did not hear anything. Try again, a little closer." else null
            },
            maxSeconds = 15, noSpeechSeconds = 8,
        )
    }
    DisposableEffect(Unit) { onDispose { capture.stop() } }
    fun go() {
        // The microphone is single-use: a running meeting recording or a voice conversation holds it.
        if (model.recording) { state.error = "Stop the meeting recording first: the microphone is in use."; return }
        got = false; state.error = null; state.recording = true; capture.start()
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> if (granted) go() else state.error = "Microphone permission is needed" }
    state.start = {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) go() else permission.launch(Manifest.permission.RECORD_AUDIO)
    }
    state.stop = { capture.stop(); state.recording = false; state.level = 0f }
    return state
}

@Composable
fun VoiceIdentityScreen(model: AppViewModel, onClose: () -> Unit) {
    val vi = model.voiceIdentity
    LaunchedEffect(Unit) { vi.refresh() }
    var gvOpen by remember { mutableStateOf(false) }
    var password by remember { mutableStateOf("") }
    var consent by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    var phoneRecognizer by remember { mutableStateOf(model.prefs.phoneRecognizer) }
    val status = vi.status
    val draft = status?.draft
    val enrolling = rememberClipRecorder(model) { vi.addSample(it) }
    val testing = rememberClipRecorder(model) { vi.test(it) }
    DisposableEffect(Unit) { onDispose { enrolling.cancel(); testing.cancel() } }

    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize().padding(horizontal = 16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClose) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
                    Text("Voice identity", style = MaterialTheme.typography.titleLarge)
                }
                Text(
                    "Reachy can check whether a spoken request sounds like you. The result is a hint shown here and in voice chat for a few seconds. It never unlocks anything: " +
                        "what you can ask for, and what needs a typed confirmation, is the same whatever it says, and typing and voice chat work without it. " +
                        "Your voice is processed on your homelab, never a cloud service. Over plain HTTP outside Tailscale, other devices on the same network could read the audio.",
                    style = MaterialTheme.typography.bodySmall,
                )
                when {
                    status == null -> Text("Checking the hub…")
                    !status.enabled -> Text("Voice identity is switched off at the hub, so voice chat uses this phone's own speech recognition.")
                    else -> {
                        Text(
                            buildString {
                                append(if (status.ready) "Speaker service ready. " else "The speaker service is not answering; voice chat still works. ")
                                append(if (status.calibrated) "Calibrated." else "Not yet calibrated: every result shows as unverified or inconclusive.")
                            },
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        status.profile?.let { Text("Enrolled: profile version ${it.version} from ${it.sampleCount} clips.", style = MaterialTheme.typography.bodyMedium) }
                            ?: Text("No voice profile yet.", style = MaterialTheme.typography.bodyMedium)
                    }
                }
                vi.message?.let { Text(it, color = MaterialTheme.colorScheme.primary) }

                if (status?.enabled == true) {
                    HorizontalDivider()
                    Text(if (status.profile == null) "Enrol your voice" else "Replace your voice profile", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Record at least five clear clips of a few seconds each. Read each phrase in your normal voice, in a quiet room. The clips are kept only in the hub's memory until you save, " +
                            "and only a mathematical summary is stored, encrypted. You can delete a clip or cancel at any time.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    val next = ENROLLMENT_PHRASES[(draft?.samples?.size ?: 0) % ENROLLMENT_PHRASES.size]
                    Text("Say: “$next”", style = MaterialTheme.typography.bodyLarge)
                    Text(draftProgress(draft, draft?.requiredSamples ?: 5), style = MaterialTheme.typography.labelLarge)
                    LinearProgressIndicator(progress = { ((draft?.usableSamples ?: 0) / (draft?.requiredSamples ?: 5).toFloat()).coerceIn(0f, 1f) }, Modifier.fillMaxWidth())
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Button({ if (enrolling.recording) enrolling.cancel() else enrolling.begin() }, enabled = !vi.busy) { Text(if (enrolling.recording) "Stop" else "Record a clip") }
                        if (enrolling.recording) LinearProgressIndicator(progress = { enrolling.level }, Modifier.weight(1f))
                    }
                    enrolling.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                    draft?.samples?.forEachIndexed { index, sample ->
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text("Clip ${index + 1}: ${if (sample.qualityOk) "good" else "not usable"}")
                                if (!sample.qualityOk) Text(reasonText(sample.reasons.firstOrNull()), style = MaterialTheme.typography.bodySmall)
                            }
                            TextButton({ vi.removeSample(sample.sampleId) }, enabled = !vi.busy) { Text("Delete") }
                        }
                    }
                    if ((draft?.samples?.size ?: 0) > 0) OutlinedButton({ vi.cancelEnrollment() }, enabled = !vi.busy) { Text("Cancel enrolment and delete all clips") }
                    Row(verticalAlignment = Alignment.Top) {
                        Checkbox(consent, { consent = it })
                        Text(
                            "I agree to Reachy storing an encrypted voice profile of my own voice on my homelab, to compare my speech with it, and to delete it whenever I choose.",
                            style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 12.dp),
                        )
                    }
                    OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth(), label = { Text("Your password, to save") }, singleLine = true, visualTransformation = PasswordVisualTransformation())
                    Button(
                        { vi.commit(password, consent) { password = ""; consent = false } },
                        enabled = !vi.busy && consent && password.isNotBlank() && (draft?.usableSamples ?: 0) >= (draft?.requiredSamples ?: 5),
                    ) { Text(if (status.profile == null) "Save voice profile" else "Replace voice profile") }

                    if (status.profile != null) {
                        HorizontalDivider()
                        Text("Try it", style = MaterialTheme.typography.titleMedium)
                        Text("Say anything. You will see how the check describes that clip; the clip is not kept.", style = MaterialTheme.typography.bodySmall)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                            Button({ if (testing.recording) testing.cancel() else testing.begin() }, enabled = !vi.busy) { Text(if (testing.recording) "Stop" else "Test my voice") }
                            if (testing.recording) LinearProgressIndicator(progress = { testing.level }, Modifier.weight(1f))
                        }
                        testing.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                        vi.testResult?.let { Text(it.label, style = MaterialTheme.typography.titleSmall); Text(it.detail, style = MaterialTheme.typography.bodySmall) }

                        HorizontalDivider()
                        Text("Delete my voice profile", style = MaterialTheme.typography.titleMedium)
                        if (!confirmDelete) OutlinedButton({ confirmDelete = true }) { Text("Delete…") }
                        else {
                            Text("This removes the stored profile and any current result. Enter your password to confirm.", style = MaterialTheme.typography.bodySmall)
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button({ vi.deleteProfile(password); confirmDelete = false; password = "" }, enabled = !vi.busy && password.isNotBlank()) { Text("Delete profile") }
                                TextButton({ confirmDelete = false }) { Text("Keep it") }
                            }
                        }
                    }
                }

                HorizontalDivider()
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Use this phone's speech recognition for voice chat")
                        Text(
                            if (phoneRecognizer) "Voice goes to the phone's recogniser, which may use a cloud service. No audio is sent to Reachy and no voice check runs."
                            else "Voice goes to Reachy's own recogniser on your homelab (when voice identity is on). Switch this on if that ever fails.",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    Switch(phoneRecognizer, { phoneRecognizer = it; model.prefs.phoneRecognizer = it })
                }

                if (status?.enabled == true) {
                    HorizontalDivider()
                    Text("Evaluation for the owner (gate GV)", style = MaterialTheme.typography.titleMedium)
                    Text("A guided recording session that measures how well the check works. Not needed for everyday use.", style = MaterialTheme.typography.bodySmall)
                    OutlinedButton({ gvOpen = true }) { Text("Open voice evaluation") }
                }
                Text("", Modifier.padding(24.dp))
            }
        }
    }
    if (gvOpen) GvScreen(model) { gvOpen = false }
}
