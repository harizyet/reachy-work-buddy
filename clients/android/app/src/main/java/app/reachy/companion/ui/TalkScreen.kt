package app.reachy.companion.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import app.reachy.companion.data.sourceLabel
import app.reachy.companion.data.safeUrl
import app.reachy.companion.data.citedPieces
import app.reachy.companion.data.WebSource
import app.reachy.companion.data.Piece
import androidx.compose.ui.unit.sp
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.material3.TextButton
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material3.FilledIconButton
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import androidx.compose.material3.AssistChip
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
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
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import app.reachy.companion.AppViewModel
import app.reachy.companion.SpeechInput
import app.reachy.companion.SpeechOutput

@Composable
fun TalkScreen(model: AppViewModel, speakReplies: Boolean, modifier: Modifier = Modifier) {
    ReadableWidth(modifier, 760) { TalkContent(model, speakReplies) }
}

@Composable
private fun TalkContent(model: AppViewModel, speakReplies: Boolean) {
    val context = LocalContext.current
    var draft by remember { mutableStateOf("") }
    var micError by remember { mutableStateOf<String?>(null) }
    // Full-screen voice conversation: listen, send, speak the reply, listen again, until it is closed.
    var voiceMode by remember { mutableStateOf(false) }
    var muted by remember { mutableStateOf(false) }
    var phase by remember { mutableStateOf(VoicePhase.Listening) }
    var heard by remember { mutableStateOf("") }
    var level by remember { mutableFloatStateOf(0f) }
    var seqAtSend by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    val output = remember { SpeechOutput(context) }
    val listenAgain = remember { mutableStateOf({}) }
    val input = remember {
        SpeechInput(
            context,
            onPartial = { heard = it },
            onFinal = { heard = ""; seqAtSend = model.replySeq; phase = VoicePhase.Thinking; model.send(it, spoken = true) },
            onEnd = { error ->
                level = 0f
                if (error != null) { micError = error; muted = true; phase = VoicePhase.Muted }
                // Silence or no match is not an error: keep listening, unless the text was just sent.
                else if (voiceMode && phase == VoicePhase.Listening) listenAgain.value()
            },
            onLevel = { level = it },
        )
    }
    DisposableEffect(Unit) { onDispose { input.stop(); output.shutdown() } }
    fun startListening() { output.stop(); micError = null; heard = ""; phase = VoicePhase.Listening; muted = false; input.start() }
    listenAgain.value = { scope.launch { delay(300); if (voiceMode && phase == VoicePhase.Listening && !muted) input.start() } }
    // After Reachy has spoken (or a turn failed) the conversation carries on, unless the microphone was switched off.
    fun afterReply() { if (!voiceMode) return; if (muted) phase = VoicePhase.Muted else startListening() }
    // The hub streams its voice sentence by sentence; the phone's own voice covers a hub that cannot speak.
    var phoneVoice by remember { mutableStateOf(model.prefs.phoneVoice) }
    fun speakReply(reply: String, done: () -> Unit) {
        if (phoneVoice) { output.speak(reply, done); return }
        output.playStream(scope, { onRate, onPcm -> model.replyStream(reply, onRate, onPcm) }, { output.speak(reply, done) }, done)
    }
    LaunchedEffect(model.replySeq, speakReplies) {
        val reply = model.lastReply
        val seq = model.replySeq
        // Each reply is read aloud once. This effect runs again whenever the screen is rebuilt (changing tab, folding the
        // phone, toggling the setting), and must not read an old reply again.
        val fresh = seq > model.spokenSeq
        model.spokenSeq = seq
        if (voiceMode) {
            // Replies are always spoken in voice mode, and the loop resumes when the voice has finished.
            if (reply != null && fresh) {
                phase = VoicePhase.Speaking
                speakReply(reply) { afterReply() }
            }
        } else if (speakReplies && reply != null && fresh) {
            // Reachy's own voice first, so replies sound like the robot; the phone's voice when the hub cannot speak or the
            // audio cannot be played.
            speakReply(reply) {}
        } else if (!speakReplies) output.stop()
    }
    // A turn that failed produces no reply to wait for: go back to listening.
    LaunchedEffect(model.sending) {
        if (!model.sending && voiceMode && phase == VoicePhase.Thinking && model.replySeq == seqAtSend) afterReply()
    }
    fun openVoice() { voiceMode = true; startListening() }
    fun closeVoice() { voiceMode = false; input.stop(); output.stop(); heard = ""; level = 0f }
    fun toggleMute() {
        if (muted) { muted = false; if (phase == VoicePhase.Muted) startListening() }
        else { muted = true; if (phase == VoicePhase.Listening) { input.stop(); phase = VoicePhase.Muted; heard = "" } }
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) openVoice() else micError = "Microphone permission is needed to talk"
    }
    fun openVoiceChecked() {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) openVoice()
        else permission.launch(Manifest.permission.RECORD_AUDIO)
    }

    if (voiceMode) {
        VoiceModeScreen(phase, heard, level, micError ?: model.chatStatus, muted, phoneVoice, { phoneVoice = it; model.prefs.phoneVoice = it; output.stop() }, { toggleMute() }, { closeVoice() })
    }

    val listState = rememberLazyListState()
    LaunchedEffect(model.chat.size) { if (model.chat.isNotEmpty()) listState.animateScrollToItem(model.chat.lastIndex) }

    Column(Modifier.fillMaxSize().imePadding()) {
        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (model.chat.isEmpty()) {
                Column(Modifier.align(Alignment.Center).padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("Talk to Reachy", style = MaterialTheme.typography.headlineSmall)
                    Text(
                        "Tap the voice button to talk with Reachy, or type below. Ask it to add a task, set an alarm or remember something.",
                        style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp),
                    )
                }
            }
            LazyColumn(state = listState, contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(model.chat) { line -> Bubble(line.text, line.fromOwner, line.failed, line.context, line.sources, line.searchFailed) }
                if (model.sending) item { Text("Reachy is thinking…", style = MaterialTheme.typography.bodySmall) }
            }
        }
        model.contextMeeting?.let { (_, title) ->
            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                AssistChip(
                    onClick = { model.clearContext() },
                    label = { Text("Meeting context: $title  ✕", maxLines = 1) },
                )
            }
            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                FilterChip(model.contextCloud, { model.contextCloud = !model.contextCloud }, { Text("Ask the cloud model") })
            }
            Text(
                if (model.contextCloud) "Cloud: this meeting's text is sent to your cloud provider for a stronger answer."
                else "Questions are answered from this meeting using the local model; the transcript stays on your homelab.",
                style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(horizontal = 16.dp),
                color = if (model.contextCloud) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
            )
        }
        (micError ?: model.chatStatus)?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 16.dp)) }
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                draft, { draft = it }, Modifier.weight(1f), placeholder = { Text("Message Reachy") }, maxLines = 4,
            )
            IconButton(
                { model.send(draft); draft = "" }, enabled = draft.isNotBlank() && !model.sending,
            ) { Icon(Icons.AutoMirrored.Filled.Send, "Send") }
            FilledIconButton({ openVoiceChecked() }, enabled = !model.sending) { Icon(Icons.Default.GraphicEq, "Voice mode") }
        }
    }
}

@Composable
private fun Bubble(
    text: String, fromOwner: Boolean, failed: Boolean, context: String? = null,
    sources: List<WebSource> = emptyList(), searchFailed: Boolean = false,
) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (fromOwner) Arrangement.End else Arrangement.Start) {
        // Selectable so a reply (or what was heard) can be long-pressed, highlighted and copied.
        SelectionContainer {
        Column(
            Modifier.widthIn(max = 300.dp)
                .background(
                    if (fromOwner) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant,
                    RoundedCornerShape(16.dp),
                ).padding(12.dp),
        ) {
            // Rendered as plain text: replies and echoed input are never interpreted as markup. Citation markers [S1] become
            // tappable links to the source the web search returned, when that source has a safe http(s) address.
            Text(
                buildAnnotatedString {
                    for (piece in citedPieces(text, sources)) when (piece) {
                        is Piece.Text -> append(piece.text)
                        is Piece.Cite -> withLink(
                            LinkAnnotation.Url(
                                piece.url!!,
                                TextLinkStyles(SpanStyle(color = MaterialTheme.colorScheme.primary, textDecoration = TextDecoration.Underline, fontSize = 12.sp)),
                            ),
                        ) { append(piece.label) }
                    }
                },
            )
            if (sources.isNotEmpty()) {
                val uriHandler = LocalUriHandler.current
                Text("Sources", style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(top = 8.dp))
                sources.forEachIndexed { index, source ->
                    val url = safeUrl(source.url)
                    val label = sourceLabel(index, source)
                    if (url != null) TextButton({ uriHandler.openUri(url) }, contentPadding = PaddingValues(0.dp)) {
                        Text(label, style = MaterialTheme.typography.bodySmall, textDecoration = TextDecoration.Underline)
                    } else Text(label, style = MaterialTheme.typography.bodySmall)
                }
            } else if (searchFailed) Text("The web search was unavailable for this answer.", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
            if (context != null) Text("From the meeting “$context”", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.secondary)
            if (failed) Text("Reply not received", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
        }
        }
    }
}
