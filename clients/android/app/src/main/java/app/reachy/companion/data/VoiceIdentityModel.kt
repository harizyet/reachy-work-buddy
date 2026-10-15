package app.reachy.companion.data

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import java.util.UUID

/**
 * State and actions for voice enrolment, the owner-match display and the GV evaluation clips (Phase 32A.V). Audio comes in as a finished WAV
 * and goes straight to the hub; nothing is stored here beyond the last result, which expires. Whatever happens here, ordinary voice chat and
 * signing in are not affected: a failure only produces a message.
 */
class VoiceIdentityModel(
    private val scope: CoroutineScope,
    private val api: () -> ReachyApi,
    private val who: () -> ClientIdentity,
    private val phoneRecognizer: () -> Boolean,
    private val now: () -> Long = System::currentTimeMillis,
) {
    var status by mutableStateOf<VoiceIdentityStatus?>(null); private set
    var busy by mutableStateOf(false); private set
    var message by mutableStateOf<String?>(null)
    private var last by mutableStateOf<Pair<VoiceStateView, Long>?>(null)
    var testResult by mutableStateOf<OwnerMatch?>(null); private set
    var gv by mutableStateOf<BenchmarkStatus?>(null); private set

    /** Voice chat sends its audio to Reachy's speech recogniser (and the speaker check) when the hub has the feature on and the owner has not chosen the phone's. */
    val hubCapture: Boolean get() = status?.enabled == true && !phoneRecognizer()

    val calibrated: Boolean get() = status?.calibrated == true

    /** The last spoken turn's result while it is current, else null: there is no lasting badge. */
    fun match(nowMs: Long = now()): OwnerMatch? =
        last?.let { (view, at) -> currentMatch(view, at, nowMs)?.let { ownerMatch(it, calibrated) } }

    fun clear() { status = null; last = null; testResult = null; gv = null; message = null; busy = false }

    private fun fail(e: Exception): String = when {
        e is ApiException && e.unauthorized && e.message?.contains("password", true) == true -> "That password is not right."
        e is ApiException && e.unauthorized -> "Please enter your password again."
        e is ApiException && e.code == 404 -> "Voice identity is not switched on at the hub."
        e is ApiException && e.code == 503 -> "The speaker service is not available. Voice chat still works."
        e is ApiException && e.code == 409 -> when (e.message) {
            "consent_required" -> "Tick the consent box to save your voice profile."
            "not_enough_samples" -> "Not enough good clips yet."
            "inconsistent_samples" -> "The clips do not sound like one person. Delete the odd ones, or start again."
            "draft_full" -> "That is enough clips. Save the profile or delete some."
            else -> e.message ?: "Not accepted."
        }
        e is ApiException -> e.message ?: "Request failed"
        else -> "Could not reach the hub."
    }

    private fun launch(block: suspend () -> Unit) {
        if (busy) return
        busy = true; message = null
        scope.launch { try { block() } catch (e: Exception) { message = fail(e) } finally { busy = false } }
    }

    fun refresh() {
        scope.launch { status = try { api().voiceIdentityStatus() } catch (e: Exception) { if (e is ApiException && e.unauthorized) status else VoiceIdentityStatus() } }
    }

    fun addSample(wav: ByteArray) = launch {
        val sample = api().addEnrollmentSample(wav, who())
        message = if (sample.qualityOk) "Clip added." else "Clip not usable: ${reasonText(sample.reasons.firstOrNull())}"
        status = api().voiceIdentityStatus()
    }

    fun removeSample(id: String) = launch { api().removeEnrollmentSample(id); status = api().voiceIdentityStatus() }

    /** Cancel: drops every clip of the unsaved enrolment, on the hub as well as here. */
    fun cancelEnrollment() = launch { api().discardEnrollment(); status = api().voiceIdentityStatus(); message = "Enrolment cancelled. Nothing was saved." }

    /** Saving or replacing a profile needs the password again (a fresh sign-in check) and the consent box. */
    fun commit(password: String, consent: Boolean, done: () -> Unit = {}) = launch {
        if (!consent) { message = fail(ApiException(409, "consent_required", null)); return@launch }
        api().reauthenticate(password)
        api().commitEnrollment(true, who())
        status = api().voiceIdentityStatus(); last = null; message = "Voice profile saved."
        done()
    }

    fun deleteProfile(password: String) = launch {
        api().reauthenticate(password)
        api().deleteVoiceProfile()
        status = api().voiceIdentityStatus(); last = null; testResult = null; message = "Voice profile deleted."
    }

    /** One spoken test clip: the answer is shown, never stored. */
    fun test(wav: ByteArray) = launch {
        val view = api().verifyVoice(wav, who(), UUID.randomUUID().toString())
        testResult = ownerMatch(view, calibrated)
        last = view to now()
    }

    /** The voice-chat path: one upload gives the transcript and the owner-match result. Throws on failure; a missing result is not an error. */
    suspend fun transcribe(wav: ByteArray): String {
        val turn = api().voiceTurn(wav, who(), UUID.randomUUID().toString())
        turn.voice?.let { last = it to now() }
        return turn.transcript
    }

    // ---- GV evaluation ----

    fun refreshGv() { scope.launch { gv = try { api().benchmarkStatus() } catch (e: Exception) { gv } } }

    /** Evaluation clips are raw audio kept on the hub until deleted, so collection is an explicit switch behind the password. */
    fun enableGv(password: String) = launch {
        api().reauthenticate(password)
        api().setBenchmarkEnabled(true)
        gv = api().benchmarkStatus(); message = "Evaluation recording is on."
    }

    fun uploadGv(step: GvStep, wav: ByteArray, alias: String?) = launch {
        api().uploadBenchmarkClip(wav, gvLabel(step, alias))
        gv = api().benchmarkStatus(); message = "Clip saved for ${step.title.lowercase()}."
    }

    fun deleteGvClips(password: String) = launch {
        api().reauthenticate(password)
        api().deleteBenchmarkClips()
        api().setBenchmarkEnabled(false)
        gv = api().benchmarkStatus(); message = "All evaluation clips deleted and recording switched off."
    }
}
