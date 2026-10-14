package app.reachy.companion.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

// Supervised meeting-minutes email (Phase 55, ADR 0039). The owner prepares a package from a finished meeting, reviews exactly what will go out, approves it by typing SEND, and the hub's
// server sends it through the dedicated sender after a ten-minute window the owner can cancel. Nothing here sends anything by itself and the phone never holds a credential: the server owns the
// state machine, the approval hash and the sender. The pure helpers below decide only what the screen enables.

@Serializable
data class EmailRecipients(val to: List<String> = emptyList(), val cc: List<String> = emptyList(), val bcc: List<String> = emptyList())

@Serializable
data class EmailAttachment(val name: String, @SerialName("content_type") val contentType: String = "application/pdf", val sha256: String = "", val size: Int = 0)

@Serializable
data class EmailEvent(val at: String = "", val event: String, val detail: Map<String, JsonElement> = emptyMap())

@Serializable
data class EmailDraft(
    val id: String,
    val subject: String,
    val body: String,
    val status: String,
    val recipients: EmailRecipients = EmailRecipients(),
    val attachments: List<EmailAttachment> = emptyList(),
    @SerialName("package_hash") val packageHash: String? = null,
    @SerialName("approved_hash") val approvedHash: String? = null,
    val sender: String? = null,
    @SerialName("dispatch_at") val dispatchAt: String? = null,
    @SerialName("sent_at") val sentAt: String? = null,
    @SerialName("created_at") val createdAt: String = "",
    val attempts: Int = 0,
    @SerialName("last_error") val lastError: String? = null,
    @SerialName("provider_response") val providerResponse: String? = null,
    @SerialName("meeting_changed") val meetingChanged: Boolean = false,
    @SerialName("sender_ready") val senderReady: Boolean = false,
    @SerialName("recipient_count") val recipientCount: Int = 0,
    val warnings: List<String> = emptyList(),
    val events: List<EmailEvent> = emptyList(),
)

@Serializable
data class EmailSender(
    val enabled: Boolean = false,
    val configured: Boolean = false,
    @SerialName("from_address") val fromAddress: String = "",
)

@Serializable
data class EmailConfig(
    val enabled: Boolean = false,
    val sender: EmailSender? = null,
    @SerialName("send_delay_seconds") val sendDelaySeconds: Int = 600,
)

@Serializable
data class EmailGroup(val id: String, val name: String, val addresses: List<String> = emptyList())

@Serializable
data class EmailSuggestion(val address: String, val source: String = "")

const val CONFIRM_WORD = "SEND"
val EDITABLE_STATUSES = setOf("draft", "ready_for_review", "approved")

fun emailStatusLabel(status: String): String = when (status) {
    "draft" -> "Draft"
    "ready_for_review" -> "Ready for your review"
    "approved" -> "Approved, not queued"
    "queued" -> "Queued: will be sent unless you cancel"
    "sending" -> "Sending…"
    "sent" -> "Sent"
    "cancelled" -> "Discarded"
    "rejected" -> "Rejected"
    "failed" -> "Not sent: it failed"
    "unknown_delivery" -> "Delivery unknown"
    else -> status
}

fun emailEventLabel(event: String): String = when (event) {
    "prepared" -> "Prepared"
    "edited" -> "Edited"
    "approved" -> "Approved by you"
    "queued" -> "Queued to send"
    "cancelled_before_send" -> "Cancelled before sending"
    "discarded" -> "Discarded"
    "sending" -> "Sending attempt"
    "retry_scheduled" -> "Could not connect; will retry"
    "sent" -> "Sent"
    "failed" -> "Failed"
    "unknown_delivery" -> "Delivery unknown"
    "owner_confirmed_delivered" -> "You confirmed it arrived"
    "owner_reopened" -> "You chose to send it again"
    else -> event
}

/** One address per line, comma or semicolon; blanks dropped, order kept, no duplicates. The server validates every address; this only splits what the owner typed. */
fun splitAddresses(text: String): List<String> = text.split('\n', ',', ';').map { it.trim() }.filter { it.isNotEmpty() }.distinct()

fun joinAddresses(addresses: List<String>): String = addresses.joinToString("\n")

/** What the form currently holds, to compare with what the server holds. */
data class EmailForm(val to: String, val cc: String, val bcc: String, val subject: String, val body: String, val attachPdf: Boolean)

fun formOf(draft: EmailDraft) = EmailForm(joinAddresses(draft.recipients.to), joinAddresses(draft.recipients.cc), joinAddresses(draft.recipients.bcc), draft.subject, draft.body, draft.attachments.isNotEmpty())

/** Unsaved changes mean the screen shows something the server does not hold, so it cannot be approved. */
fun isDirty(draft: EmailDraft, form: EmailForm): Boolean = form != formOf(draft)

/** The approval button is enabled only for a saved, reviewed message that has a To recipient and whose typed word is right. */
fun canApprove(draft: EmailDraft, form: EmailForm, typed: String, busy: Boolean): Boolean =
    draft.status == "ready_for_review" && !busy && !isDirty(draft, form) && draft.recipients.to.isNotEmpty() && typed.trim().equals(CONFIRM_WORD, ignoreCase = true)

/** A queued message can be cancelled; a message whose delivery is unknown is settled by the owner, never retried by the app. */
fun canCancelSend(draft: EmailDraft) = draft.status == "queued"
fun needsOwnerResolution(draft: EmailDraft) = draft.status == "unknown_delivery"
fun isEditable(draft: EmailDraft) = draft.status in EDITABLE_STATUSES
fun isActive(draft: EmailDraft) = draft.status == "queued" || draft.status == "sending"

/** The complete delivery list, one line per field, as the review shows it. Bcc is labelled so the owner knows it is hidden from the others. */
fun reviewLines(draft: EmailDraft): List<String> = buildList {
    add("From: ${draft.sender ?: "(sender not set)"}")
    add("To: ${draft.recipients.to.joinToString(", ").ifEmpty { "(nobody yet)" }}")
    if (draft.recipients.cc.isNotEmpty()) add("Cc: ${draft.recipients.cc.joinToString(", ")}")
    if (draft.recipients.bcc.isNotEmpty()) add("Bcc (hidden from the others): ${draft.recipients.bcc.joinToString(", ")}")
    add("Subject: ${draft.subject}")
    if (draft.attachments.isEmpty()) add("No attachment.")
    draft.attachments.forEach { add("Attachment: ${it.name} (${maxOf(1, it.size / 1024)} KB, fingerprint ${it.sha256.take(12)})") }
}
