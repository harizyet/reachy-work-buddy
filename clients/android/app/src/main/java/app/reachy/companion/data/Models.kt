package app.reachy.companion.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class Task(val id: String, val text: String, val status: String = "open") {
    val done get() = status == "done"
}

@Serializable
data class Note(val id: String, val title: String, val body: String = "")

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
    @SerialName("speaker_names") val speakerNames: Map<String, String> = emptyMap(),
    @SerialName("transcript_corrections") val corrections: Map<String, String> = emptyMap(),
    @SerialName("key_terms") val keyTerms: List<String> = emptyList(),
    val summary: MeetingOutput? = null,
    val minutes: MeetingOutput? = null,
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
)

@Serializable
data class WebSource(val title: String = "", val url: String = "", val snippet: String = "", @SerialName("source_domain") val sourceDomain: String = "")

@Serializable
data class WebSearch(val query: String = "", val failed: Boolean = false, val results: List<WebSource> = emptyList())

@Serializable
data class ChatRecord(val id: String, val title: String = "")

@Serializable
data class StatusInfo(@SerialName("default_user_id") val defaultUserId: String? = null)

@Serializable
data class Receipt(
    @SerialName("action_type") val actionType: String,
    val status: String = "success",
    val at: String = "",
    val fields: Map<String, String> = emptyMap(),
)
