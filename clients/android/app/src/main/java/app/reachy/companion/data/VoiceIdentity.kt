package app.reachy.companion.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.io.ByteArrayOutputStream
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.sqrt

// Shared voice identity on the phone (Phase 32A.V, ADR 0041). Pure logic, tested on the JVM. A voice result is identity evidence for one
// utterance: nothing in this file lets it change what the owner may do, and nothing here is persisted (audio and results live in memory).

const val CAPTURE_RATE = 16000
private const val FRAME_MS = 30
const val FRAME_SAMPLES = CAPTURE_RATE * FRAME_MS / 1000

/** Mono 16 kHz PCM16 in a canonical 44-byte-header WAV: the one capture format the hub's speech recogniser and the speaker service both read. */
object Wav {
    fun encode(pcm: ShortArray, length: Int = pcm.size, rate: Int = CAPTURE_RATE): ByteArray {
        val data = length * 2
        val out = ByteArrayOutputStream(44 + data)
        fun int(v: Int) { out.write(v and 0xFF); out.write((v shr 8) and 0xFF); out.write((v shr 16) and 0xFF); out.write((v shr 24) and 0xFF) }
        fun short(v: Int) { out.write(v and 0xFF); out.write((v shr 8) and 0xFF) }
        out.write("RIFF".toByteArray()); int(36 + data); out.write("WAVE".toByteArray())
        out.write("fmt ".toByteArray()); int(16); short(1); short(1); int(rate); int(rate * 2); short(2); short(16)
        out.write("data".toByteArray()); int(data)
        for (i in 0 until length) short(pcm[i].toInt())
        return out.toByteArray()
    }
}

fun frameDbfs(frame: ShortArray, count: Int = frame.size): Float {
    if (count == 0) return -120f
    var sum = 0.0
    for (i in 0 until count) { val x = frame[i] / 32768.0; sum += x * x }
    return (20 * log10(sqrt(sum / count) + 1e-6)).toFloat()
}

/**
 * Decides when one spoken utterance starts and ends, from per-frame levels. Fed one 30 ms frame at a time. It is an energy gate, not a speech
 * detector: the threshold follows the room's noise floor, but a loud fan can still look like speech, which is why the hub transcribes the
 * clip and refuses an empty transcript.
 */
class Endpointer(
    private val noSpeechFrames: Int = 8000 / FRAME_MS,
    private val maxFrames: Int = 20000 / FRAME_MS,
    private val endSilenceFrames: Int = 1000 / FRAME_MS,
    private val startFrames: Int = 5,
    private val minSpeechFrames: Int = 500 / FRAME_MS,
) {
    enum class Event { Waiting, Speaking, Ended, NoSpeech, TooLong }

    private val floorWindow = ArrayList<Float>()
    private var floor = -60f
    private var frames = 0
    private var run = 0
    private var silent = 0
    private var speechFrames = 0
    var firstSpeechFrame = -1; private set
    var started = false; private set
    val frameCount get() = frames

    /** Level above which a frame counts as speech. */
    val threshold get() = max(-45f, floor + 10f)

    fun feed(dbfs: Float): Event {
        frames++
        if (floorWindow.size < 15) {
            floorWindow.add(dbfs)
            floor = floorWindow.sorted()[floorWindow.size / 5]   // the quiet fifth of the first half-second
        }
        val loud = dbfs > threshold && frames > 3   // the first frames can carry the recorder's start-up click
        if (!started) {
            run = if (loud) run + 1 else 0
            if (run >= startFrames) { started = true; firstSpeechFrame = frames - run; speechFrames = run; silent = 0 }
            else if (frames >= noSpeechFrames) return Event.NoSpeech
        } else {
            if (loud) { silent = 0; speechFrames++ } else silent++
            if (silent >= endSilenceFrames) {
                if (speechFrames >= minSpeechFrames) return Event.Ended
                started = false; run = 0; speechFrames = 0; firstSpeechFrame = -1   // a click, not a sentence: start over
            }
        }
        if (frames >= maxFrames) return if (started) Event.TooLong else Event.NoSpeech
        return if (started) Event.Speaking else Event.Waiting
    }

    /** The sample range worth keeping: a little lead-in before the first speech frame, through the last frame fed. */
    fun keepFrom(): Int = max(0, firstSpeechFrame - 10) * FRAME_SAMPLES
}

// ---- hub models ------------------------------------------------------------------------------------------

@Serializable
data class VoiceStateView(
    val state: String,
    @SerialName("utterance_id") val utteranceId: String = "",
    @SerialName("expires_in_seconds") val expiresInSeconds: Double = 0.0,
    val reasons: List<String> = emptyList(),
)

@Serializable
data class VoiceProfileInfo(val version: Int = 1, @SerialName("sample_count") val sampleCount: Int = 0, @SerialName("model_version") val modelVersion: String = "", @SerialName("created_at") val createdAt: String = "")

@Serializable
data class DraftSample(@SerialName("sample_id") val sampleId: String, @SerialName("quality_ok") val qualityOk: Boolean, val reasons: List<String> = emptyList(), @SerialName("speech_seconds") val speechSeconds: Double = 0.0)

@Serializable
data class EnrollmentDraft(
    val samples: List<DraftSample> = emptyList(),
    @SerialName("usable_samples") val usableSamples: Int = 0,
    @SerialName("required_samples") val requiredSamples: Int = 5,
)

@Serializable
data class VoiceIdentityStatus(
    val enabled: Boolean = false,
    val ready: Boolean = false,
    val profile: VoiceProfileInfo? = null,
    val draft: EnrollmentDraft? = null,
    val reauthenticated: Boolean = false,
    val calibrated: Boolean = false,
)

@Serializable
data class VoiceTurnResult(val transcript: String = "", val voice: VoiceStateView? = null)

@Serializable
data class BenchmarkClip(@SerialName("sample_id") val sampleId: String, val label: String? = null)

@Serializable
data class BenchmarkStatus(
    @SerialName("benchmark_enabled") val benchmarkEnabled: Boolean = false,
    @SerialName("voice_samples") val voiceSamples: List<BenchmarkClip> = emptyList(),
)

// ---- what the screen says ----------------------------------------------------------------------------------

enum class MatchKind { Unverified, Inconclusive, NotVerified, Verified, NoProfile, Unavailable }

data class OwnerMatch(val kind: MatchKind, val label: String, val detail: String)

/**
 * The wording for one result. Until the owner has approved a calibration nothing is ever shown as verified, whatever the hub says: a
 * "verified" from an uncalibrated hub is shown as Unverified. A result describes one utterance and says nothing about permissions.
 */
fun ownerMatch(view: VoiceStateView, calibrated: Boolean): OwnerMatch {
    val reason = view.reasons.firstOrNull()
    return when {
        view.state == "unavailable" && reason == "no_profile" -> OwnerMatch(MatchKind.NoProfile, "No voice profile", "Enrol your voice to see a match.")
        view.state == "unavailable" && reason == "not_calibrated" -> OwnerMatch(MatchKind.Unverified, "Owner match: unverified", "Checking is switched on but not yet calibrated, so no result counts.")
        view.state == "unavailable" -> OwnerMatch(MatchKind.Unavailable, "Voice check unavailable", unavailableReason(reason))
        view.state == "uncertain" -> OwnerMatch(MatchKind.Inconclusive, "Owner match: inconclusive", reasonText(reason))
        !calibrated -> OwnerMatch(MatchKind.Unverified, "Owner match: unverified", "Not yet calibrated, so this result does not count.")
        view.state == "verified" -> OwnerMatch(MatchKind.Verified, "Owner voice verified", "This only describes this one utterance.")
        else -> OwnerMatch(MatchKind.NotVerified, "Owner match: not verified", "Typing and signing in are unaffected.")
    }
}

fun reasonText(reason: String?): String = when (reason) {
    "too_little_speech" -> "Too little speech in that clip."
    "too_quiet" -> "Too quiet. Move closer or speak up."
    "clipped" -> "Too loud; the sound is distorted."
    "" , null -> "The clip was not clear enough to judge."
    else -> "The clip could not be used."
}

private fun unavailableReason(reason: String?) = when (reason) {
    "service_unavailable" -> "The speaker service did not answer. Voice chat still works."
    "model_changed_reenroll" -> "The voice model changed. Enrol again."
    "profile_unreadable", "storage_unavailable" -> "The hub could not read the voice profile."
    else -> "Voice chat still works."
}

/** A result is shown only while it is current; afterwards the screen shows nothing rather than a stale badge. */
fun currentMatch(view: VoiceStateView?, receivedAtMs: Long, nowMs: Long): VoiceStateView? =
    view?.takeIf { nowMs - receivedAtMs < (it.expiresInSeconds * 1000).toLong() }

val ENROLLMENT_PHRASES = listOf(
    "The quick brown fox jumps over the lazy dog.",
    "Please remind me to call the dentist on Thursday morning.",
    "What is on my calendar for tomorrow afternoon?",
    "Add milk, eggs and a loaf of bread to the shopping list.",
    "Set an alarm for half past six and read me the weather.",
    "My voice is my own, and I am enrolling it on my own phone.",
    "Reachy, summarise the meeting we had on Monday.",
    "Nine green bottles stood on the shelf by the window.",
)

fun draftProgress(draft: EnrollmentDraft?, required: Int = 5): String {
    val usable = draft?.usableSamples ?: 0
    return if (usable >= required) "$usable good clips: ready to save" else "$usable of $required good clips"
}

// ---- headers ----------------------------------------------------------------------------------------------

/** Provenance the hub records for audit; asserted by this install, not an authentication. */
fun provenanceHeaders(installId: String, deviceName: String, utteranceId: String? = null): Map<String, String> = buildMap {
    put("X-Reachy-Client-Kind", "android")
    put("X-Reachy-Client-Id", installId.take(64))
    if (deviceName.isNotBlank()) put("X-Reachy-Device-Id", deviceName.filter { it.isLetterOrDigit() || it in " -_." }.take(64))
    if (utteranceId != null) put("X-Reachy-Utterance-Id", utteranceId)
}

// ---- GV evaluation protocol --------------------------------------------------------------------------------

/** One block of the guided evaluation. `role`/`speaker`/`condition` become the clip's label on the hub. */
data class GvStep(
    val id: String, val title: String, val instruction: String, val role: String, val speaker: String, val condition: String,
    val target: Int, val nonOwner: Boolean = false, val attack: Boolean = false,
)

val GV_PLAN = listOf(
    GvStep("enroll", "Enrolment clips", "Owner. Speak the phrase shown, one clip each, in a quiet room, holding the phone as you normally would.", "enroll", "owner", "enroll", 8),
    GvStep("quiet", "Owner, quiet room", "Owner. Free speech, 4 to 8 seconds, quiet room.", "trial", "owner", "quiet", 10),
    GvStep("noisy", "Owner, background noise", "Owner. Same, with a TV, tap or street noise playing.", "trial", "owner", "noisy", 10),
    GvStep("held_out", "Owner, another day", "Owner. Record these at least one day after the enrolment clips, so they are genuinely held out.", "trial", "owner", "held_out", 10),
    GvStep("other_person", "Someone else (with their consent)", "A person who agreed to be recorded for this test, speaking normally. Use an alias, never a real name.", "trial", "person1", "other_person", 10, nonOwner = true),
    GvStep("replay", "Replay probe", "Play a recording of the owner's voice from a second device, near this phone, and capture it. Say nothing yourself.", "trial", "owner", "replay", 6, attack = true),
    GvStep("synthetic", "Synthetic voice probe", "Play computer-generated speech (a text-to-speech voice, or voice-converted speech if you have it) near this phone.", "trial", "owner", "synthetic", 6, attack = true),
)

fun gvLabel(step: GvStep, alias: String? = null): String =
    "role=${step.role};speaker=${if (step.nonOwner) cleanAlias(alias ?: step.speaker) else step.speaker};condition=${step.condition}"

fun cleanAlias(raw: String): String = raw.filter { it.isLetterOrDigit() || it == '_' || it == '-' }.take(32).ifBlank { "person1" }

/** How many clips of each condition the hub already holds, from the labels it reports. */
fun gvCounts(clips: List<BenchmarkClip>): Map<String, Int> =
    clips.mapNotNull { it.label }.mapNotNull { label -> label.split(";").firstOrNull { it.startsWith("condition=") }?.removePrefix("condition=") }
        .groupingBy { it }.eachCount()

fun gvComplete(counts: Map<String, Int>): Boolean = GV_PLAN.all { (counts[it.condition] ?: 0) >= it.target }
