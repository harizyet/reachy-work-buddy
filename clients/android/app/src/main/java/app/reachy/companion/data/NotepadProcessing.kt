package app.reachy.companion.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.security.MessageDigest

// Notepad processing (Phase 49), as on the web. The owner sends a saved note to Reachy; Reachy proposes tasks and reminders; nothing becomes a task or reminder until the
// owner accepts it. The hub serves these routes to the signed-in owner only and decides everything; this file only shapes what it sends. Kinds, states and statuses stay
// strings so a value added later on the server shows as-is instead of failing the whole screen.

@Serializable
data class ProposalSource(
    val kind: String = "note", val quote: String = "",
    @SerialName("meeting_id") val meetingId: String? = null, val title: String? = null, val speaker: String? = null,
)

@Serializable
data class Proposal(
    val id: String, val kind: String, val status: String, val text: String,
    val sources: List<ProposalSource> = emptyList(),
    @SerialName("evidence_from") val evidenceFrom: String = "note",
    @SerialName("due_at") val dueAt: String? = null,
    val ambiguity: List<String> = emptyList(),
    @SerialName("source_changed") val sourceChanged: Boolean = false,
    @SerialName("record_id") val recordId: String? = null,
) {
    val open get() = status == "pending" || status == "accepting"
}

@Serializable
data class JobMeeting(
    @SerialName("meeting_id") val meetingId: String, val title: String = "", val included: Boolean = false, val reason: String? = null,
)

@Serializable
data class ProcessingJob(val id: String, val status: String = "queued", val error: String? = null, val meetings: List<JobMeeting> = emptyList())

@Serializable
data class Processing(
    @SerialName("note_id") val noteId: String,
    val state: String = "not_processed",
    val job: ProcessingJob? = null,
    @SerialName("note_changed_since_job") val noteChangedSinceJob: Boolean = false,
    val proposals: List<Proposal> = emptyList(),
) {
    /** The server is still working on it, so the screen keeps asking. */
    val inProgress get() = state == "queued" || state == "processing"
}

@Serializable
data class LinkedMeeting(
    val id: String, val title: String = "", @SerialName("started_at") val startedAt: String? = null,
    @SerialName("transcript_ready") val transcriptReady: Boolean = false,
)

@Serializable
data class MeetingLink(
    val id: String, @SerialName("meeting_id") val meetingId: String, val state: String = "suggested", val meeting: LinkedMeeting? = null,
) {
    val confirmed get() = state == "confirmed"
}

@Serializable
data class MeetingLinks(val links: List<MeetingLink> = emptyList())

val PROCESSING_STATE_LABEL = mapOf(
    "not_processed" to "Not processed", "queued" to "Queued", "processing" to "Processing",
    "review_required" to "Review required", "completed" to "Completed", "failed" to "Failed",
)
val PROPOSAL_KIND_LABEL = mapOf("task" to "Task", "reminder" to "Reminder", "event" to "Possible event (review only)", "reference" to "Information")
val PROPOSAL_FROM_LABEL = mapOf("note" to "From the note", "transcript" to "From a meeting transcript", "both" to "From the note and a meeting transcript")
private val FAILURE_LABEL = mapOf(
    "model_unavailable" to "The local model was not available.", "bad_model_output" to "The model’s answer could not be used.",
    "timeout" to "Processing took too long.", "internal_error" to "Something went wrong.",
)

fun processingFailure(code: String?): String = FAILURE_LABEL[code] ?: "Processing failed."

/** SHA-256 of the note text as saved. The server compares it with its own hash of the stored body, so a note edited elsewhere is not processed under the wrong text. */
fun noteHash(body: String): String = MessageDigest.getInstance("SHA-256").digest(body.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
