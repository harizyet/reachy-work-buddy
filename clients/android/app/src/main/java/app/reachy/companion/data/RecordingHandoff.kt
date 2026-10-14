package app.reachy.companion.data

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/*
 * "Reachy, begin meeting recording" in voice mode. A deterministic, on-device command: the spoken sentence is matched here and never sent to the hub, and nothing the
 * hub or the model says can start a recording. The handoff below orders the steps (spoken confirmation, end the voice conversation, start the existing recorder, wait
 * for the recorder to say it is running); it is pure so the ordering and the stale-callback guards are tested on the JVM.
 */

private val lead = Regex("^(?:(?:hey|ok|okay)\\s+)?reachy\\s+")
private val polite = Regex("^(?:please\\s+|(?:can|could|would)\\s+you\\s+(?:please\\s+)?)")
private val trail = Regex("\\s+please$")
private val subject = "(?:this |the |a |my |our )?"
private val phrases = listOf(
    Regex("^(?:begin|start) $subject" + "meeting recording$"),
    Regex("^(?:begin|start) recording $subject" + "meeting$"),
    Regex("^record $subject" + "meeting$"),
)

/**
 * True only when the whole utterance is one of the explicit commands ("begin meeting recording", "start recording this meeting", "record this meeting", with an optional
 * "Reachy", "please" or "can you"). A question or a longer sentence that merely mentions recording ("what happens when I record a meeting") is ordinary conversation.
 */
fun isMeetingRecordingCommand(spoken: String): Boolean {
    var text = spoken.lowercase().replace(Regex("[^a-z ]"), " ").trim().replace(Regex("\\s+"), " ")
    text = text.replace(lead, "").replace(polite, "").replace(trail, "")
    return phrases.any { it.matches(text) }
}

/** What Reachy says before the voice conversation ends. */
const val RECORDING_CONFIRMATION = "Okay, I'll end our conversation and start recording the meeting."

enum class HandoffState { Idle, Confirming, EndingVoice, StartingRecording }

sealed interface RecorderResult {
    data object Active : RecorderResult
    data class Failed(val message: String) : RecorderResult
}

sealed interface HandoffOutcome {
    /** The recorder reported that it is recording. */
    data object Started : HandoffOutcome
    /** A recording was already running, so nothing was started and the voice conversation carries on. */
    data object AlreadyRecording : HandoffOutcome
    /** Nothing was recorded, and [message] says why. [resumeVoice] is true when the voice conversation was not ended, so it can listen again. */
    data class Failed(val message: String, val resumeVoice: Boolean) : HandoffOutcome
    data class Cancelled(val message: String) : HandoffOutcome
}

class RecordingHandoff(private val scope: CoroutineScope, private val host: Host) {
    interface Host {
        fun microphoneAllowed(): Boolean
        fun recordingActive(): Boolean
        /** The app is on screen and focused: Android refuses to start a microphone service from the background. */
        fun appInForeground(): Boolean
        /** Speak [RECORDING_CONFIRMATION] and report the end through [confirmationFinished] with [operation]. False when nothing can speak. */
        fun speakConfirmation(operation: Int): Boolean
        /** Stop listening, stop and release playback and close the voice screen. Synchronous: the microphone is free when it returns. */
        fun endVoice()
        /** Asks the existing recorder to start; throws if the request cannot even be made. */
        fun requestRecorderStart()
        /** Suspends until the recorder is running or has failed. */
        suspend fun awaitRecorder(): RecorderResult
        fun finished(outcome: HandoffOutcome)
    }

    var state: HandoffState = HandoffState.Idle; private set
    val busy get() = state != HandoffState.Idle

    /** Bumped for every handoff and every cancellation: a callback that carries an older number is stale and ignored. */
    private var operation = 0

    /**
     * The command was recognised. Returns false (and does nothing) when a handoff is already running. [speak] is false for a typed command: there is no voice
     * conversation to announce or end, so the handoff goes straight to the same re-checks and recorder start.
     */
    fun begin(speak: Boolean = true): Boolean {
        if (busy) return false
        if (!host.microphoneAllowed()) { fail("Microphone permission is needed to record. Allow it, then ask again.", resume = true); return true }
        if (host.recordingActive()) { host.finished(HandoffOutcome.AlreadyRecording); return true }
        if (!host.appInForeground()) { fail("Recording was not started because the app is not on screen.", resume = true); return true }
        val mine = ++operation
        state = HandoffState.Confirming
        if (!speak) { confirmationFinished(mine, true); return true }
        if (!host.speakConfirmation(mine)) fail("Reachy could not speak the confirmation, so recording was not started.", resume = true, mine)
        return true
    }

    /** The confirmation finished ([spoken] true) or failed. A stale or repeated report is ignored. */
    fun confirmationFinished(mine: Int, spoken: Boolean) {
        if (mine != operation || state != HandoffState.Confirming) return
        if (!spoken) { fail("The spoken confirmation did not finish, so recording was not started.", resume = true, mine); return }
        // Re-checked here: the owner may have left the app, revoked the microphone or started a recording while Reachy was speaking.
        if (!host.microphoneAllowed()) { fail("Microphone permission is needed to record. Allow it, then ask again.", resume = true, mine); return }
        if (host.recordingActive()) { state = HandoffState.Idle; host.finished(HandoffOutcome.AlreadyRecording); return }
        if (!host.appInForeground()) { fail("Recording was not started because the app left the screen.", resume = true, mine); return }
        state = HandoffState.EndingVoice
        host.endVoice()
        if (mine != operation) return   // cancelled while the voice conversation was closing
        state = HandoffState.StartingRecording
        try { host.requestRecorderStart() } catch (e: Exception) { fail("Could not start recording", resume = false, mine); return }
        scope.launch {
            val result = host.awaitRecorder()
            if (mine != operation || state != HandoffState.StartingRecording) return@launch
            state = HandoffState.Idle
            host.finished(if (result is RecorderResult.Failed) HandoffOutcome.Failed(result.message, resumeVoice = false) else HandoffOutcome.Started)
        }
    }

    /**
     * The owner closed voice mode, left the screen or the Talk screen went away. Before the recorder has been asked to start this stops the handoff; after that it cannot,
     * because the recording is already starting (and the recording bar's Stop is the way out), so this returns false and changes nothing.
     */
    fun cancel(message: String): Boolean {
        if (state == HandoffState.Idle) return true
        if (state == HandoffState.StartingRecording) return false
        operation++
        state = HandoffState.Idle
        host.finished(HandoffOutcome.Cancelled(message))
        return true
    }

    private fun fail(message: String, resume: Boolean, mine: Int = operation) {
        if (mine != operation) return
        state = HandoffState.Idle
        host.finished(HandoffOutcome.Failed(message, resume))
    }
}
