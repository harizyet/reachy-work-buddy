package app.reachy.companion.ui

import android.graphics.Bitmap
import android.graphics.Color as AndroidColor
import android.graphics.pdf.PdfRenderer
import android.os.ParcelFileDescriptor
import androidx.compose.foundation.Image
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.reachy.companion.AppViewModel
import app.reachy.companion.data.EmailDraft
import app.reachy.companion.data.Meeting
import app.reachy.companion.data.canApprove
import app.reachy.companion.data.canCancelSend
import app.reachy.companion.data.emailEventLabel
import app.reachy.companion.data.emailStatusLabel
import app.reachy.companion.data.formOf
import app.reachy.companion.data.isDirty
import app.reachy.companion.data.isEditable
import app.reachy.companion.data.joinAddresses
import app.reachy.companion.data.needsOwnerResolution
import app.reachy.companion.data.reviewLines
import app.reachy.companion.data.splitAddresses
import app.reachy.companion.data.EmailForm
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Share minutes (Phase 55): prepare the summary and minutes as an email, review exactly what will go out, approve it by typing SEND, and it waits for the hub's undo window before the
 * server sends it. Nothing here sends anything by itself. The phone holds no credential; the hub's server owns the state machine, the approval hash and the sender.
 */
@Composable
fun ShareMinutes(model: AppViewModel, meeting: Meeting, modifier: Modifier = Modifier) {
    LaunchedEffect(meeting.id) { model.loadEmail(meeting.id) }
    val open = model.emailDrafts.firstOrNull { it.id == model.openEmailId }
    var includePdf by remember { mutableStateOf(true) }
    var sensitive by remember { mutableStateOf(false) }

    LazyColumn(modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Text(
                "Prepare the summary and minutes as an email, review exactly what will go out, and approve it. Nothing is sent without your approval, and a message waits " +
                    "${model.emailDelayMinutes} minutes so you can still cancel it.",
                style = MaterialTheme.typography.bodySmall,
            )
            if (!model.emailSenderConfigured) Text("Set up the outbound sender first, in the web Settings (Accounts, Outbound meeting email).", Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall, color = GapText)
            else if (!model.emailSenderReady) Text("Sending is turned off. You can prepare and review a message, but it cannot be queued until sending is enabled in the web Settings.", Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall, color = GapText)
            if (meeting.staleOutputs.isNotEmpty()) Text(
                "The ${meeting.staleOutputs.joinToString(" and ")} was written before the speaker names changed. Write it again before preparing a message.",
                Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall, color = GapText,
            )
        }
        if (open != null) {
            item { DraftView(model, open) }
        } else {
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text("Prepare a message", style = MaterialTheme.typography.titleSmall)
                        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                            Switch(includePdf, { includePdf = it }, Modifier.semantics { contentDescription = "Attach the minutes as a PDF" })
                            Text("  Attach the minutes as a PDF", style = MaterialTheme.typography.bodyMedium)
                        }
                        if (model.emailNeedsAck) Row(verticalAlignment = androidx.compose.ui.Alignment.Top) {
                            Checkbox(sensitive, { sensitive = it }, Modifier.semantics { contentDescription = "Confirm sensitive meeting" })
                            Text("This meeting is marked sensitive. I understand and want to prepare a message from it.", style = MaterialTheme.typography.bodySmall, color = GapText)
                        }
                        Button({ model.prepareEmail(meeting.id, includePdf, sensitive) }, Modifier.padding(top = 8.dp), enabled = !model.emailBusy && (!model.emailNeedsAck || sensitive)) {
                            Text(if (model.emailBusy) "Preparing…" else "Prepare message")
                        }
                    }
                }
            }
            if (model.emailDrafts.isNotEmpty()) {
                item { Text("Messages for this meeting", style = MaterialTheme.typography.titleSmall) }
                items(model.emailDrafts, key = { it.id }) { draft ->
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp)) {
                            Text(draft.subject, style = MaterialTheme.typography.titleSmall)
                            Text("${emailStatusLabel(draft.status)} · ${draft.recipientCount} recipient${if (draft.recipientCount == 1) "" else "s"} · ${draft.createdAt.take(16).replace('T', ' ')}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
                            TextButton({ model.openEmailId = draft.id }, Modifier.semantics { contentDescription = "Open message ${draft.subject}" }) { Text("Open") }
                        }
                    }
                }
            }
        }
        model.emailNote?.let { item { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error, modifier = Modifier.semantics { contentDescription = "Share minutes error" }) } }
    }
}

@Composable
private fun DraftView(model: AppViewModel, draft: EmailDraft) {
    var form by remember(draft.packageHash, draft.status) { mutableStateOf(formOf(draft)) }
    var typed by remember(draft.packageHash, draft.status) { mutableStateOf("") }
    val editable = isEditable(draft)
    val dirty = isDirty(draft, form)

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            Text(draft.subject, Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
            TextButton({ model.openEmailId = null; model.openMeetingId()?.let { model.loadEmail(it) } }) { Text("Back") }
        }
        Text(emailStatusLabel(draft.status), Modifier.semantics { contentDescription = "Message status: ${emailStatusLabel(draft.status)}" }, style = MaterialTheme.typography.labelLarge)
        draft.warnings.forEach { Text(it, style = MaterialTheme.typography.bodySmall, color = GapText) }
        if (draft.meetingChanged && editable) {
            Text("The meeting's summary, minutes or speaker names changed after this message was prepared, so it cannot be queued as it is.", style = MaterialTheme.typography.bodySmall, color = GapText)
            TextButton({ model.refreshEmail(draft.id) }) { Text("Refresh it from the meeting") }
        }

        if (editable) {
            AddressField("To (one address per line)", form.to) { form = form.copy(to = it) }
            AddressField("Cc", form.cc) { form = form.copy(cc = it) }
            AddressField("Bcc (hidden from the other recipients)", form.bcc) { form = form.copy(bcc = it) }
            if (model.emailGroups.isNotEmpty()) Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                model.emailGroups.forEach { g ->
                    TextButton({ form = form.copy(to = joinAddresses((splitAddresses(form.to) + g.addresses).distinct())) }, Modifier.semantics { contentDescription = "Add group ${g.name}" }) { Text("+ ${g.name}") }
                }
            }
            if (model.emailSuggestions.isNotEmpty()) {
                Text("Suggested from the calendar (nothing is added unless you choose it)", style = MaterialTheme.typography.labelSmall)
                model.emailSuggestions.forEach { s ->
                    val chosen = splitAddresses(form.to).contains(s.address)
                    Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                        Checkbox(chosen, { on -> form = form.copy(to = joinAddresses(if (on) (splitAddresses(form.to) + s.address).distinct() else splitAddresses(form.to) - s.address)) }, Modifier.semantics { contentDescription = "Suggested ${s.address}" })
                        Text("${s.address} (${s.source})", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            OutlinedTextField(form.subject, { form = form.copy(subject = it.take(200)) }, Modifier.fillMaxWidth(), label = { Text("Subject") }, singleLine = true)
            OutlinedTextField(form.body, { form = form.copy(body = it) }, Modifier.fillMaxWidth(), label = { Text("Message") }, minLines = 8)
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Switch(form.attachPdf, { form = form.copy(attachPdf = it) }, Modifier.semantics { contentDescription = "Attach the minutes as a PDF" })
                Text("  Attach the minutes as a PDF", style = MaterialTheme.typography.bodyMedium)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button({ model.saveEmail(draft.id, form) }, enabled = dirty && !model.emailBusy) { Text("Save changes") }
                TextButton({ model.discardEmail(draft.id) }, enabled = !model.emailBusy) { Text("Discard message") }
            }
            if (dirty) Text("You have unsaved changes. Save them, then review the message again before approving.", style = MaterialTheme.typography.bodySmall, color = GapText)
        } else {
            Text(draft.body, style = MaterialTheme.typography.bodySmall)
        }

        Card(Modifier.fillMaxWidth().semantics { contentDescription = "What will be sent" }) {
            Column(Modifier.padding(12.dp)) {
                Text("What will be sent", style = MaterialTheme.typography.titleSmall)
                reviewLines(draft).forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                Text("The recording and the raw transcript are never included.", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
                draft.attachments.firstOrNull()?.let { PdfPreview(model, draft.id, it.name) }
            }
        }

        if (draft.status == "ready_for_review") {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) {
                    Text("Approve this exact message", style = MaterialTheme.typography.titleSmall)
                    Text("It goes from ${draft.sender ?: "the configured sender"} to ${draft.recipientCount} recipient${if (draft.recipientCount == 1) "" else "s"} (listed above) after a ${model.emailDelayMinutes}-minute window. Any later change needs a new approval.", style = MaterialTheme.typography.bodySmall)
                    if (!draft.senderReady) Text("Sending is turned off, so approving will not queue it.", style = MaterialTheme.typography.bodySmall, color = GapText)
                    OutlinedTextField(typed, { typed = it }, Modifier.fillMaxWidth().padding(top = 4.dp), label = { Text("Type SEND to approve") }, singleLine = true)
                    Button({ model.approveEmail(draft, typed) }, Modifier.padding(top = 8.dp), enabled = canApprove(draft, form, typed, model.emailBusy)) {
                        Text(if (draft.senderReady) "Approve and queue" else "Approve")
                    }
                }
            }
        }
        if (draft.status == "approved") Button({ model.queueEmail(draft.id) }, enabled = !model.emailBusy && draft.senderReady && !draft.meetingChanged) { Text("Queue for sending") }
        if (canCancelSend(draft)) {
            Text("Queued. It will be sent at ${draft.dispatchAt?.take(16)?.replace('T', ' ') ?: "the scheduled time"} (UTC) unless you cancel.", style = MaterialTheme.typography.bodyMedium)
            Button({ model.cancelEmailSend(draft.id) }, enabled = !model.emailBusy) { Text("Cancel sending") }
        }
        if (draft.status == "sent") Text("Sent ${draft.sentAt?.take(16)?.replace('T', ' ') ?: ""}${draft.providerResponse?.let { " (server reply: $it)" } ?: ""}.", style = MaterialTheme.typography.bodyMedium)
        if (draft.status == "failed") Text("This message was not sent. ${draft.lastError.orEmpty()} Nothing was delivered. Prepare a new message to try again.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error)
        if (needsOwnerResolution(draft)) {
            Text(
                "Reachy could not confirm whether this message was delivered (${draft.lastError ?: "no answer from the mail server"}). It will not be sent again automatically, to avoid a duplicate. " +
                    "Check the recipient or the sender's Sent folder, then tell Reachy what happened.",
                style = MaterialTheme.typography.bodySmall, color = GapText,
            )
            Button({ model.resolveEmail(draft.id, true) }, enabled = !model.emailBusy) { Text("It arrived") }
            TextButton({ model.resolveEmail(draft.id, false) }, enabled = !model.emailBusy) { Text("It did not arrive: send it again (needs a new approval)") }
            TextButton({ model.discardEmail(draft.id) }, enabled = !model.emailBusy) { Text("Discard") }
        }

        Text("History", style = MaterialTheme.typography.titleSmall)
        draft.events.forEach { Text("${it.at.take(16).replace('T', ' ')}: ${emailEventLabel(it.event)}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline) }
    }
}

@Composable
private fun AddressField(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(value, onChange, Modifier.fillMaxWidth(), label = { Text(label) }, minLines = 1, maxLines = 4)
}

/** The attachment exactly as it will be sent: fetched with the owner's session, then drawn page by page in the app (no external viewer, nothing is shared). */
@Composable
private fun PdfPreview(model: AppViewModel, draftId: String, name: String) {
    var shown by remember(draftId, name) { mutableStateOf(false) }
    var pages by remember(draftId, name) { mutableStateOf<List<Bitmap>>(emptyList()) }
    var failure by remember(draftId, name) { mutableStateOf<String?>(null) }
    TextButton({ shown = !shown }, Modifier.semantics { contentDescription = if (shown) "Hide PDF preview" else "Preview PDF" }) { Text(if (shown) "Hide preview" else "Preview PDF") }
    if (shown) {
        LaunchedEffect(draftId, name) {
            try { pages = withContext(Dispatchers.IO) { renderPdf(model.fetchEmailAttachment(draftId, name)) }; failure = null }
            catch (e: Exception) { failure = "Could not show the preview: ${e.message ?: "unknown error"}" }
        }
        failure?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
        pages.forEachIndexed { index, bitmap ->
            Image(bitmap.asImageBitmap(), "Page ${index + 1} of the PDF", Modifier.fillMaxWidth().padding(vertical = 4.dp), contentScale = ContentScale.FillWidth)
        }
    }
}

private fun renderPdf(file: File): List<Bitmap> {
    val out = mutableListOf<Bitmap>()
    ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY).use { fd ->
        PdfRenderer(fd).use { renderer ->
            for (index in 0 until minOf(renderer.pageCount, 12)) {
                renderer.openPage(index).use { page ->
                    val scale = 1.6f
                    val bitmap = Bitmap.createBitmap((page.width * scale).toInt(), (page.height * scale).toInt(), Bitmap.Config.ARGB_8888)
                    bitmap.eraseColor(AndroidColor.WHITE)
                    page.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                    out += bitmap
                }
            }
        }
    }
    return out
}
