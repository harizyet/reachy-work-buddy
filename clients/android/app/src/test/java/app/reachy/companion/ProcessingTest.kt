package app.reachy.companion

import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.ReachyApi
import app.reachy.companion.data.noteHash
import app.reachy.companion.data.processingFailure
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Notepad processing (Phase 49) against a mock hub: the same routes and bodies the web client uses. */
class ProcessingTest {
    private lateinit var server: MockWebServer
    private var stored: String? = null
    private lateinit var api: ReachyApi

    @Before fun setUp() {
        server = MockWebServer().apply { start() }
        api = ReachyApi(server.url("/hub").toString(), PersistentCookieJar({ stored }, { stored = it }))
    }

    @After fun tearDown() = server.shutdown()

    private fun ok(body: String) = server.enqueue(MockResponse().setBody(body).setHeader("Content-Type", "application/json"))
    private fun body(request: okhttp3.mockwebserver.RecordedRequest) = Json.parseToJsonElement(request.body.readUtf8()).jsonObject

    private val review = """
        {"note_id":"n1","state":"review_required","note_changed_since_job":true,
         "job":{"id":"j1","status":"succeeded","error":null,"model":"qwen","proposal_count":2,"meetings":[{"meeting_id":"m1","title":"Standup","included":false,"reason":"transcript not ready"}]},
         "proposals":[
          {"id":"p1","note_id":"n1","kind":"task","status":"pending","text":"Spin up a gitlab repo","evidence":"spin up gitlab","evidence_from":"both","ambiguity":["Which server?"],"source_changed":false,
           "sources":[{"kind":"note","quote":"spin up gitlab repo","meeting_id":null,"title":null,"speaker":null},{"kind":"meeting","quote":"we need git","meeting_id":"m1","title":"Standup","speaker":"Stephen"}],
           "stated_time":null,"due_at":null,"record_kind":null,"record_id":null,"edited":false,"future_field":1},
          {"id":"p2","note_id":"n1","kind":"reminder","status":"accepted","text":"Call Lisa","evidence":"","sources":[],"evidence_from":"note","due_at":"2030-01-02T09:00:00Z","ambiguity":[],"record_kind":"reminder","record_id":"r9"}]}"""

    @Test fun `a hub with processing off, or an older hub, reads as off and any other failure is not hidden`() = runBlocking {
        ok("""{"enabled":true}""")
        assertTrue(api.processingEnabled())
        assertEquals("/hub/notepad-processing/config", server.takeRequest().path)
        ok("""{"enabled":false}""")
        assertFalse(api.processingEnabled())
        server.enqueue(MockResponse().setResponseCode(404).setBody("""{"detail":"Not Found"}"""))
        assertFalse(api.processingEnabled())
        server.enqueue(MockResponse().setResponseCode(502).setBody("""{"detail":"core down"}"""))
        try { api.processingEnabled(); throw AssertionError("expected a failure") } catch (e: app.reachy.companion.data.ApiException) { assertEquals(502, e.code) }
    }

    @Test fun `processing state, proposals with their evidence and unknown fields are read`() = runBlocking {
        ok(review)
        val p = api.processing("n1")
        assertEquals("/hub/notes/n1/processing", server.takeRequest().path)
        assertEquals("review_required", p.state)
        assertTrue(p.noteChangedSinceJob && !p.inProgress)
        assertEquals(listOf(false), p.job!!.meetings.map { it.included })
        assertEquals(listOf("p1"), p.proposals.filter { it.open }.map { it.id })
        val first = p.proposals[0]
        assertEquals(listOf("note", "meeting"), first.sources.map { it.kind })
        assertEquals("Stephen", first.sources[1].speaker)
        assertEquals("both", first.evidenceFrom)
        assertEquals("r9", p.proposals[1].recordId)
    }

    @Test fun `sending a note carries the hash of its text and the meeting choice, and a queued note is in progress`() = runBlocking {
        ok("""{"note_id":"n1","state":"queued","job":{"id":"j1","status":"queued"},"proposals":[],"created":true}""")
        val p = api.sendForProcessing("n1", noteHash("milk"), force = true, includeMeetings = true)
        assertTrue(p.inProgress)
        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/hub/notes/n1/processing", request.path)
        assertEquals("1", request.getHeader("X-Reachy-CSRF"))
        val sent = body(request)
        assertEquals(noteHash("milk"), sent["expected_hash"]!!.jsonPrimitive.content)
        assertEquals(true, sent["force"]!!.jsonPrimitive.booleanOrNull)
        assertEquals(true, sent["include_meetings"]!!.jsonPrimitive.booleanOrNull)
    }

    @Test fun `accepting sends only what the owner changed and dismissing and retrying use their own routes`() = runBlocking {
        ok("{}"); api.acceptProposal("p1")
        var request = server.takeRequest()
        assertEquals("/hub/notepad-proposals/p1/accept", request.path)
        assertTrue(body(request).isEmpty())
        ok("{}"); api.acceptProposal("p1", text = "Call Lisa", kind = "reminder", dueAt = "2030-01-02T09:00:00Z")
        val edited = body(server.takeRequest())
        assertEquals(setOf("text", "kind", "due_at"), edited.keys)
        assertEquals("reminder", edited["kind"]!!.jsonPrimitive.content)
        ok("{}"); api.dismissProposal("p2")
        assertEquals("/hub/notepad-proposals/p2/dismiss", server.takeRequest().path)
        ok("""{"note_id":"n1","state":"queued","job":{"id":"j2","status":"queued"},"proposals":[]}"""); api.retryProcessing("j1")
        assertEquals("/hub/notepad-processing/jobs/j1/retry", server.takeRequest().path)
    }

    @Test fun `meeting links are listed and a link is confirmed or rejected`() = runBlocking {
        val links = """{"links":[{"id":"l1","meeting_id":"m1","source":"temporal","state":"suggested","title_match":false,"meeting_missing":false,
            "meeting":{"id":"m1","title":"Standup","started_at":"2026-10-09T08:00:00Z","transcript_ready":true}}]}"""
        ok(links)
        val listed = api.meetingLinks("n1")
        assertEquals("/hub/notes/n1/meeting-links", server.takeRequest().path)
        assertEquals(listOf(false), listed.map { it.confirmed })
        assertTrue(listed[0].meeting!!.transcriptReady)
        ok(links.replace("suggested", "confirmed"))
        assertTrue(api.setMeetingLink("n1", "m1", true)[0].confirmed)
        val put = server.takeRequest()
        assertEquals("PUT", put.method); assertEquals("/hub/notes/n1/meeting-links/m1", put.path)
        assertEquals("confirmed", body(put)["state"]!!.jsonPrimitive.content)
        ok("""{"links":[]}"""); api.setMeetingLink("n1", "m1", false)
        server.takeRequest().let { assertEquals("rejected", body(it)["state"]!!.jsonPrimitive.content) }
    }

    @Test fun `the note hash is the SHA-256 of the stored text and failures read plainly`() {
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", noteHash("abc"))
        assertEquals(noteHash("café"), noteHash("café"))
        assertTrue(noteHash("a") != noteHash("a "))
        assertEquals("The local model was not available.", processingFailure("model_unavailable"))
        assertEquals("Processing failed.", processingFailure(null))
    }
}
