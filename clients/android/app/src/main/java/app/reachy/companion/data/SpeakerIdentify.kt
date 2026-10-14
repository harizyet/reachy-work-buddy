package app.reachy.companion.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// Identify Speakers (Phase 54). The server picks a few clear stretches of the recording per detected speaker; the owner listens and names them. A sample is a time range of the
// meeting recording, played by the same player as the transcript; nothing about a voice is stored or sent. Everything the owner decides is saved in one request, and the hub decides
// what it means for the transcript, summaries and analysis.

@Serializable
data class SpeakerSample(
    val start: Double,
    val end: Double,
    val quality: String = "good",
    val notes: List<String> = emptyList(),
    val text: String = "",
)

@Serializable
data class SpeakerIdentityRecord(val status: String, val name: String? = null, @SerialName("contact_id") val contactId: String? = null)

@Serializable
data class SpeakerCard(
    val label: String,
    @SerialName("display_name") val displayName: String,
    val seconds: Double = 0.0,
    val lines: Int = 0,
    val samples: List<SpeakerSample> = emptyList(),
    val alternates: List<SpeakerSample> = emptyList(),
    val reason: String? = null,
    val identity: SpeakerIdentityRecord? = null,
)

/** Names the owner confirmed against an earlier speaker detection; kept to read, never applied. */
@Serializable
data class SupersededIdentities(val identities: Map<String, SpeakerIdentityRecord> = emptyMap())

@Serializable
data class SpeakerIdentityState(val superseded: SupersededIdentities? = null)

@Serializable
data class IdentifyScreen(
    @SerialName("meeting_id") val meetingId: String,
    val fingerprint: String? = null,
    val speakers: List<SpeakerCard> = emptyList(),
    val suggestions: List<String> = emptyList(),
    @SerialName("needs_review") val needsReview: Boolean = false,
    val superseded: SupersededIdentities? = null,
)

/** What the owner did to one speaker on this screen. [UNTOUCHED] is not a decision: nothing is sent for it. */
enum class Mode { UNTOUCHED, NAME, UNKNOWN, SKIPPED }

data class Choice(val mode: Mode = Mode.UNTOUCHED, val name: String = "")

/** One entry of the save request: `status` is named, unknown, skipped or clear. */
data class SpeakerDecision(val status: String, val name: String? = null)

fun initialChoice(card: SpeakerCard): Choice {
    val identity = card.identity ?: return Choice()
    return when (identity.status) {
        "named" -> Choice(Mode.NAME, identity.name.orEmpty())
        "unknown" -> Choice(Mode.UNKNOWN)
        "skipped" -> Choice(Mode.SKIPPED)
        else -> Choice()
    }
}

/** Only what changed since the screen was loaded. Removing a saved name or decision is `clear`; Unknown and Skip never carry a name, and nothing is forced for a speaker the owner left alone. */
fun decisionsFor(cards: List<SpeakerCard>, choices: Map<String, Choice>): Map<String, SpeakerDecision> {
    val out = linkedMapOf<String, SpeakerDecision>()
    for (card in cards) {
        val choice = choices[card.label] ?: continue
        val before = initialChoice(card)
        if (choice.mode == before.mode && choice.name.trim() == before.name.trim()) continue
        when (choice.mode) {
            Mode.NAME -> if (choice.name.isNotBlank()) out[card.label] = SpeakerDecision("named", choice.name.trim()) else if (card.identity != null) out[card.label] = SpeakerDecision("clear")
            Mode.UNTOUCHED -> if (card.identity != null) out[card.label] = SpeakerDecision("clear")
            Mode.UNKNOWN -> out[card.label] = SpeakerDecision("unknown")
            Mode.SKIPPED -> out[card.label] = SpeakerDecision("skipped")
        }
    }
    return out
}

/** The samples shown for one speaker and the ones kept back for "Another sample". */
data class SamplePool(val shown: List<SpeakerSample>, val spare: List<SpeakerSample>) {
    /** Replaces [sample] with the next spare one and keeps the replaced one at the back, so repeated taps cycle through all of them. */
    fun another(sample: SpeakerSample): SamplePool {
        val next = spare.firstOrNull() ?: return this
        return SamplePool(shown.map { if (it == sample) next else it }, spare.drop(1) + sample)
    }
}

fun poolOf(card: SpeakerCard) = SamplePool(card.samples, card.alternates)

fun sampleLabel(sample: SpeakerSample): String = "${clockLabel(sample.start)}–${clockLabel(sample.end)}"

private fun clockLabel(seconds: Double): String = "%d:%02d".format(seconds.toInt() / 60, seconds.toInt() % 60)

/** True once a sample's playback has reached its end, so the player stops by itself. -1 means no range is playing. */
fun rangeFinished(positionMs: Int, endMs: Int): Boolean = endMs >= 0 && positionMs >= endMs

/** A summary or minutes written under different speaker names than the current ones may attribute things to the wrong person. */
fun Meeting.outputIsStale(kind: String): Boolean = kind in staleOutputs

/** Speaker detection was run again and the earlier names were not carried over. */
val Meeting.speakerReviewNeeded: Boolean get() = speakerIdentity.superseded?.identities?.isNotEmpty() == true
