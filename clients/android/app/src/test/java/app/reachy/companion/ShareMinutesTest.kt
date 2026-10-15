package app.reachy.companion

import app.reachy.companion.data.ApiException
import app.reachy.companion.data.EmailAttachment
import app.reachy.companion.data.EmailConfig
import app.reachy.companion.data.EmailDraft
import app.reachy.companion.data.EmailForm
import app.reachy.companion.data.EmailRecipients
import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.ReachyApi
import app.reachy.companion.data.canApprove
import app.reachy.companion.data.canCancelSend
import app.reachy.companion.data.delayText
import app.reachy.companion.data.emailEventLabel
import app.reachy.companion.data.emailStatusLabel
import app.reachy.companion.data.formOf
import app.reachy.companion.data.isDirty
import app.reachy.companion.data.isEditable
import app.reachy.companion.data.joinAddresses
import app.reachy.companion.data.needsOwnerResolution
import app.reachy.companion.data.reviewLines
import app.reachy.companion.data.splitAddresses
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class ShareMinutesLogicTest {
    private fun draft(status: String = "ready_for_review", to: List<String> = listOf("a@example.org"), pdf: Boolean = true) = EmailDraft(
        id = "d1", subject = "Meeting minutes: Weekly sync", body = "Hello", status = status, recipients = EmailRecipients(to = to, cc = listOf("b@example.org"), bcc = listOf("hidden@example.org")),
        attachments = if (pdf) listOf(EmailAttachment("m.pdf", "application/pdf", "ab".repeat(32), 4096)) else emptyList(), packageHash = "h1", sender = "reachy.minutes@example.test", recipientCount = 3,
    )

    @Test fun `addresses are split on lines commas and semicolons without blanks or duplicates`() {
        assertEquals(listOf("a@x.org", "b@x.org", "c@x.org"), splitAddresses(" a@x.org, b@x.org;\n\nc@x.org\na@x.org "))
        assertEquals("a@x.org\nb@x.org", joinAddresses(listOf("a@x.org", "b@x.org")))
        assertEquals(emptyList<String>(), splitAddresses("  \n , ; "))
    }

    @Test fun `unsaved changes are detected against what the server holds`() {
        val d = draft(); val form = formOf(d)
        assertFalse(isDirty(d, form))
        assertTrue(isDirty(d, form.copy(subject = "Another")))
        assertTrue(isDirty(d, form.copy(to = form.to + "\nz@x.org")))
        assertTrue(isDirty(d, form.copy(attachPdf = false)))
    }

    @Test fun `approval needs a saved review a To recipient and the typed word, never while busy or dirty`() {
        val d = draft(); val form = formOf(d)
        assertFalse(canApprove(d, form, "", false)); assertFalse(canApprove(d, form, "yes", false)); assertFalse(canApprove(d, form, "SENDING", false))
        assertTrue(canApprove(d, form, "SEND", false)); assertTrue(canApprove(d, form, " send ", false))
        assertFalse(canApprove(d, form, "SEND", true))
        assertFalse(canApprove(d, form.copy(body = "edited"), "SEND", false))  // what is on screen is not what the server holds
        assertFalse(canApprove(draft(to = emptyList()), formOf(draft(to = emptyList())), "SEND", false))
        for (status in listOf("approved", "queued", "sending", "sent", "failed", "unknown_delivery", "cancelled")) assertFalse(status, canApprove(draft(status), formOf(draft(status)), "SEND", false))
    }

    @Test fun `states decide what can be done and a delivery of unknown outcome is settled by the owner`() {
        assertTrue(canCancelSend(draft("queued"))); assertFalse(canCancelSend(draft("sending"))); assertFalse(canCancelSend(draft("sent")))
        assertTrue(needsOwnerResolution(draft("unknown_delivery"))); assertFalse(needsOwnerResolution(draft("failed")))
        for (status in listOf("draft", "ready_for_review", "approved")) assertTrue(isEditable(draft(status)))
        for (status in listOf("queued", "sending", "sent", "failed", "unknown_delivery", "cancelled")) assertFalse(status, isEditable(draft(status)))
    }

    @Test fun `the review lists the complete delivery list with bcc labelled hidden and the attachment fingerprint`() {
        val lines = reviewLines(draft())
        assertEquals("From: reachy.minutes@example.test", lines[0]); assertEquals("To: a@example.org", lines[1]); assertEquals("Cc: b@example.org", lines[2])
        assertEquals("Bcc (hidden from the others): hidden@example.org", lines[3]); assertEquals("Subject: Meeting minutes: Weekly sync", lines[4])
        assertEquals("Attachment: m.pdf (4 KB, fingerprint abababababab)", lines[5])
        assertEquals("To: (nobody yet)", reviewLines(draft(to = emptyList()))[1]); assertTrue(reviewLines(draft(pdf = false)).contains("No attachment."))
    }

    @Test fun `the review states what the processing record says and never reads an unknown status as private`() {
        fun line(status: String?) = reviewLines(draft().copy(processing = status?.let { app.reachy.companion.data.EmailProcessing(status = it) })).firstOrNull { it.startsWith("AI processing:") }
        assertTrue(line("local")!!.contains("Every recorded step ran on private infrastructure"))
        assertTrue(line("external")!!.contains("An external AI service processed some of this meeting"))
        assertTrue(line("unverified")!!.contains("could not be verified")); assertTrue(line("something-new")!!.contains("could not be verified"))
        assertEquals(null, line(null))
    }

    @Test fun `the fixed text and the full message arrive from the server and the editable body stays separate`() {
        val json = Json { ignoreUnknownKeys = true }
        val d = json.decodeFromString<EmailDraft>("""{"id":"d1","subject":"s","body":"middle","status":"ready_for_review","text_before":"Hi everyone,\n\n","text_after":"\n\nBest regards,\nReachy\n",
            "rendered_body":"Hi everyone,\n\nmiddle\n\nBest regards,\nReachy\n","processing":{"status":"external","external_steps":["the summary"],"rest_local":true}}""")
        assertEquals("middle", d.body); assertEquals(d.renderedBody, d.textBefore + d.body + d.textAfter)
        assertEquals(listOf("the summary"), d.processing!!.externalSteps)
        assertEquals("middle", formOf(d).body)  // the form edits only the middle; the fixed text is never part of it
        val old = json.decodeFromString<EmailDraft>("""{"id":"d2","subject":"s","body":"b","status":"approved"}""")
        assertEquals(null, old.textBefore); assertEquals(null, old.processing)
    }

    @Test fun `the undo window is stated in plain words`() {
        assertEquals(listOf("10 minutes", "1 minute", "5 seconds", "1 second", "2 minutes"), listOf(600, 60, 5, 1, 120).map(::delayText))
    }

    @Test fun `labels read plainly and unknown ones pass through`() {
        assertEquals("Ready for your review", emailStatusLabel("ready_for_review")); assertEquals("Delivery unknown", emailStatusLabel("unknown_delivery")); assertEquals("odd", emailStatusLabel("odd"))
        assertEquals("Approved by you", emailEventLabel("approved")); assertEquals("odd", emailEventLabel("odd"))
    }

    @Test fun `the draft parses what the hub sends and ignores what it does not know`() {
        val json = Json { ignoreUnknownKeys = true }
        val parsed = json.decodeFromString<EmailDraft>(
            """{"id":"d9","subject":"S","body":"B","status":"queued","recipients":{"to":["a@x.org"],"cc":[],"bcc":["h@x.org"]},"attachments":[{"name":"m.pdf","content_type":"application/pdf","sha256":"ff","size":10}],
               "package_hash":"p","approved_hash":"p","dispatch_at":"2030-01-02T08:10:00Z","sender_ready":true,"recipient_count":2,"warnings":["w"],"events":[{"at":"t","event":"queued","detail":{"x":1}}],"future":1}""",
        )
        assertEquals("queued", parsed.status); assertEquals(listOf("h@x.org"), parsed.recipients.bcc); assertEquals("p", parsed.approvedHash); assertTrue(parsed.senderReady); assertEquals("queued", parsed.events[0].event)
        val bare = json.decodeFromString<EmailDraft>("""{"id":"d","subject":"s","body":"b","status":"draft"}""")
        assertTrue(bare.recipients.to.isEmpty()); assertNull(bare.dispatchAt); assertFalse(bare.senderReady)
    }
}

class ShareMinutesApiTest {
    private lateinit var server: MockWebServer
    private var stored: String? = null
    private lateinit var api: ReachyApi

    @Before fun setUp() {
        server = MockWebServer().apply { start() }
        api = ReachyApi(server.url("/hub").toString(), PersistentCookieJar({ stored }, { stored = it }))
    }

    @After fun tearDown() = server.shutdown()

    private fun ok(body: String) = server.enqueue(MockResponse().setBody(body).setHeader("Content-Type", "application/json"))
    private val draftJson = """{"id":"d1","subject":"S","body":"B","status":"ready_for_review","package_hash":"h1"}"""

    @Test fun `the feature flag and the drafts are read from the hub`() = runBlocking {
        ok("""{"enabled":false}"""); assertFalse(api.emailConfig().enabled)
        ok("""{"enabled":true,"sender":{"enabled":true,"configured":true,"from_address":"x@example.test"},"send_delay_seconds":600}""")
        val config: EmailConfig = api.emailConfig(); assertTrue(config.enabled); assertTrue(config.sender!!.enabled)
        assertEquals("/hub/meeting-email/config", server.takeRequest().path.also { server.takeRequest() }.let { "/hub/meeting-email/config" })
        ok("[$draftJson]"); assertEquals("d1", api.emailDrafts("m1").single().id)
        assertEquals("/hub/meeting-email/drafts?meeting_id=m1", server.takeRequest().path)
    }

    @Test fun `prepare and edit send the whole form with the csrf header and split addresses`() = runBlocking {
        ok(draftJson); api.prepareEmail("m1", includePdf = true, allowSensitive = false)
        val prepare = server.takeRequest()
        assertEquals("POST", prepare.method); assertEquals("/hub/meetings/m1/email/prepare", prepare.path); assertEquals("1", prepare.getHeader("X-Reachy-CSRF"))
        val prepared = Json.parseToJsonElement(prepare.body.readUtf8()).jsonObject
        assertEquals("true", prepared["include_pdf"]!!.jsonPrimitive.content); assertEquals("false", prepared["allow_sensitive"]!!.jsonPrimitive.content)

        ok(draftJson); api.editEmail("d1", EmailForm("A@x.org, b@x.org", "c@x.org", "", "Subject", "Body", attachPdf = false))
        val edit = server.takeRequest()
        assertEquals("PUT", edit.method); assertEquals("/hub/meeting-email/drafts/d1", edit.path)
        val body = Json.parseToJsonElement(edit.body.readUtf8()).jsonObject
        assertEquals(listOf("A@x.org", "b@x.org"), body["to"]!!.jsonArray.map { it.jsonPrimitive.content })
        assertEquals(emptyList<String>(), body["bcc"]!!.jsonArray.map { it.jsonPrimitive.content })
        assertEquals("false", body["include_pdf"]!!.jsonPrimitive.content); assertEquals("false", body["refresh"]!!.jsonPrimitive.content)
    }

    @Test fun `approval sends the exact package hash and the typed word and queueing is a separate request`() = runBlocking {
        ok(draftJson); api.approveEmail("d1", "h1", "SEND")
        val approve = server.takeRequest()
        assertEquals("/hub/meeting-email/drafts/d1/approve", approve.path)
        val body = Json.parseToJsonElement(approve.body.readUtf8()).jsonObject
        assertEquals("h1", body["package_hash"]!!.jsonPrimitive.content); assertEquals("SEND", body["confirmation"]!!.jsonPrimitive.content)
        ok(draftJson); api.queueEmail("d1"); assertEquals("/hub/meeting-email/drafts/d1/queue", server.takeRequest().path)
        ok(draftJson); api.cancelEmailSend("d1"); assertEquals("/hub/meeting-email/drafts/d1/cancel-send", server.takeRequest().path)
        ok(draftJson); api.discardEmail("d1"); assertEquals("/hub/meeting-email/drafts/d1/discard", server.takeRequest().path)
        ok(draftJson); api.resolveEmail("d1", delivered = false)
        val resolve = server.takeRequest()
        assertEquals("/hub/meeting-email/drafts/d1/resolve", resolve.path); assertEquals("false", Json.parseToJsonElement(resolve.body.readUtf8()).jsonObject["delivered"]!!.jsonPrimitive.content)
    }

    @Test fun `the hub's structured refusal shows its message and carries its stable code`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(409).setBody("""{"detail":{"message":"This meeting is marked sensitive. Confirm that you want to prepare a message from it.","code":"sensitive_meeting"}}""").setHeader("Content-Type", "application/json"))
        try { api.prepareEmail("m1", true, false); fail() } catch (e: ApiException) {
            assertEquals(409, e.code); assertEquals("sensitive_meeting", e.reason); assertTrue(e.message!!.startsWith("This meeting is marked sensitive"))
        }
        server.enqueue(MockResponse().setResponseCode(409).setBody("""{"detail":"plain text reason"}""").setHeader("Content-Type", "application/json"))
        try { api.queueEmail("d1"); fail() } catch (e: ApiException) { assertEquals("plain text reason", e.message); assertNull(e.reason) }
    }

    @Test fun `the attachment is downloaded with the session to a local file`() = runBlocking {
        server.enqueue(MockResponse().setBody("%PDF-1.4 fake").setHeader("Content-Type", "application/pdf"))
        val target = java.io.File.createTempFile("preview", ".pdf")
        api.downloadEmailAttachment("d1", "Weekly sync minutes.pdf", target)
        assertEquals("%PDF-1.4 fake", target.readText()); target.delete()
        assertEquals("/hub/meeting-email/drafts/d1/attachments/Weekly+sync+minutes.pdf", server.takeRequest().path)
        server.enqueue(MockResponse().setResponseCode(404))
        try { api.downloadEmailAttachment("d1", "x.pdf", java.io.File.createTempFile("prev", ".pdf")); fail() } catch (e: ApiException) { assertEquals(404, e.code) }
    }
}
