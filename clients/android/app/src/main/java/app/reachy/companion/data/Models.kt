package app.reachy.companion.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class Task(val id: String, val text: String, val status: String = "open") {
    val done get() = status == "done"
}

@Serializable
data class Note(
    val id: String, val title: String, val body: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
    /** The note's folder under All Notes, e.g. "Projects/Project StarWars/Finance"; null when it sits directly in All Notes. */
    val tag: String? = null,
)

@Serializable
data class MeetingOutput(val text: String, val tier: String = "local", @SerialName("generated_at") val generatedAt: String = "")

@Serializable
data class Meeting(
    val id: String,
    val title: String,
    val status: String = "uploaded",
    @SerialName("error_detail") val errorDetail: String? = null,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("transcript_segments") val transcript: List<Segment>? = null,
    @SerialName("diarization_segments") val speakers: List<Segment>? = null,
    // The server-side alignment: one entry per transcript segment, with its speaker. Null until the meeting is aligned.
    @SerialName("aligned_segments") val aligned: List<Segment>? = null,
    // Stretches of the recording where the phone captured no audio, found by the server (null until checked).
    @SerialName("audio_gaps") val audioGaps: AudioGaps? = null,
    // One or two lines under the title on what the meeting covered; written by the model, editable by the owner.
    val description: String? = null,
    @SerialName("title_source") val titleSource: String = "default",
    @SerialName("speaker_names") val speakerNames: Map<String, String> = emptyMap(),
    @SerialName("transcript_corrections") val corrections: Map<String, String> = emptyMap(),
    @SerialName("key_terms") val keyTerms: List<String> = emptyList(),
    val summary: MeetingOutput? = null,
    val minutes: MeetingOutput? = null,
    // Phase 54: "summary" and/or "minutes" when written under different speaker names than the current ones.
    @SerialName("stale_outputs") val staleOutputs: List<String> = emptyList(),
    @SerialName("speaker_identity") val speakerIdentity: SpeakerIdentityState = SpeakerIdentityState(),
)

@Serializable
data class Suggestion(
    val segment: Int,
    val original: String,
    val suggested: String,
    val reason: String = "",
    @SerialName("corrected_text") val correctedText: String,
    val confidence: String = "medium",
    val source: String = "model",
)

@Serializable
data class DeepReviewJob(
    val id: String,
    @SerialName("meeting_id") val meetingId: String,
    @SerialName("meeting_title") val meetingTitle: String = "",
    val task: String = "corrections",
    val status: String = "switching",
    val stage: String = "",
    @SerialName("reachy_unavailable") val reachyUnavailable: Boolean = false,
    @SerialName("reachy_online") val reachyOnline: Boolean = false,
    @SerialName("eta_seconds") val etaSeconds: Int = 330,
    val result: Suggestions? = null,
    val error: String? = null,
) {
    val finished get() = status == "done" || status == "failed"
}

@Serializable
data class DeepReviewInfo(
    val configured: Boolean = false,
    val available: Boolean = false,
    val reason: String? = null,
    @SerialName("eta_seconds") val etaSeconds: Int = 330,
)

@Serializable
data class ReplaceResult(val meeting: Meeting, @SerialName("replaced_segments") val replacedSegments: Int)

@Serializable
data class Suggestions(val suggestions: List<Suggestion> = emptyList(), @SerialName("checked_segments") val checkedSegments: Int = 0, val truncated: Boolean = false, @SerialName("terms_used") val termsUsed: Int = 0, @SerialName("candidates_checked") val candidatesChecked: Int = 0)

@Serializable
data class Segment(val start: Double = 0.0, val end: Double = 0.0, val text: String = "", val speaker: String? = null)

@Serializable
data class Reply(
    val reply: String,
    @SerialName("context_meeting") val contextMeeting: String? = null,
    @SerialName("web_search") val webSearch: WebSearch? = null,
    /** The title of the attached document this reply was answered from, and the pages whose excerpts were supplied. */
    @SerialName("context_document") val contextDocument: String? = null,
    val citations: List<Citation> = emptyList(),
)

@Serializable
data class WebSource(val title: String = "", val url: String = "", val snippet: String = "", @SerialName("source_domain") val sourceDomain: String = "")

@Serializable
data class WebSearch(val query: String = "", val failed: Boolean = false, val results: List<WebSource> = emptyList())

@Serializable
data class ChatRecord(val id: String, val title: String = "", @SerialName("updated_at") val updatedAt: String = "")

/** One saved exchange in a chat record: what was typed and, when it was recorded, the reply. */
@Serializable
data class ChatTurnRecord(
    val text: String, val reply: String? = null, val status: String = "complete",
    @SerialName("web_search") val webSearch: WebSearch? = null,
    val document: ChatDocument? = null,
    val citations: List<Citation> = emptyList(),
)

/** [document] is the chat's server-held attachment; `available` is false when the document has since been deleted. */
@Serializable
data class ChatDetail(val id: String, val title: String = "", val turns: List<ChatTurnRecord> = emptyList(), val document: ChatDocument? = null)

@Serializable
data class StatusInfo(@SerialName("default_user_id") val defaultUserId: String? = null)

@Serializable
data class Receipt(
    @SerialName("action_type") val actionType: String,
    val status: String = "success",
    val at: String = "",
    val fields: Map<String, String> = emptyMap(),
)

@Serializable
data class AudioGaps(val seconds: Double = 0.0, val segments: List<Int> = emptyList())
