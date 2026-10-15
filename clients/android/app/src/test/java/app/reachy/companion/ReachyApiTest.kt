package app.reachy.companion

import app.reachy.companion.data.ApiException
import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.ReachyApi
import app.reachy.companion.data.normalizeBaseUrl
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
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
import java.io.File

class ReachyApiTest {
    private lateinit var server: MockWebServer
    private var stored: String? = null
    private lateinit var api: ReachyApi

    @Before fun setUp() {
        server = MockWebServer().apply { start() }
        api = ReachyApi(server.url("/hub").toString(), PersistentCookieJar({ stored }, { stored = it }))
    }

    @After fun tearDown() = server.shutdown()

    private fun ok(body: String) = server.enqueue(MockResponse().setBody(body).setHeader("Content-Type", "application/json"))

    @Test fun `normalizes the hub address`() {
        assertEquals("http://192.168.1.2:8080/hub", normalizeBaseUrl(" 192.168.1.2:8080/hub/ "))
        assertEquals("https://home.example/hub", normalizeBaseUrl("https://home.example/hub"))
    }

    @Test fun `every request carries the CSRF header and the session cookie is kept after login`() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"username":"owner"}""").addHeader("Set-Cookie", "session=abc; Path=/; HttpOnly; Max-Age=3600"))
        api.login("owner", "pw")
        val login = server.takeRequest()
        assertEquals("/hub/auth/login", login.path)
        assertEquals("1", login.getHeader("X-Reachy-CSRF"))
        assertTrue(stored!!.contains("session=abc"))

        ok("""{"username":"owner"}""")
        assertEquals("owner", api.me())
        assertEquals("session=abc", server.takeRequest().getHeader("Cookie"))
    }

    @Test fun `a reply is streamed in Reachys voice and an unavailable voice is reported not thrown`() = runBlocking {
        server.enqueue(MockResponse().setBody("PCMDATA!").addHeader("Content-Type", "audio/L16").addHeader("X-Sample-Rate", "22050"))
        var rate = 0
        val received = java.io.ByteArrayOutputStream()
        assertTrue(api.speechStream("Hello there", { rate = it }, { buffer, count -> received.write(buffer, 0, count) }))
        assertEquals(22050, rate)
        assertEquals("PCMDATA!", received.toString())
        val request = server.takeRequest()
        assertEquals("/hub/speech/stream", request.path)
        assertEquals("Hello there", Json.parseToJsonElement(request.body.readUtf8()).jsonObject["text"]!!.jsonPrimitive.content)
        server.enqueue(MockResponse().setResponseCode(503).setBody("""{"detail":"Speech is not available"}"""))
        assertFalse(api.speechStream("Hello", { rate = -1 }, { _, _ -> }))
        assertEquals(22050, rate)   // no audio format was announced for the failed call
    }

    @Test fun `alarms are added by clock time, switched, edited and deleted through the planner routes`() = runBlocking {
        ok("""{"id":"a1","label":"Gym","due_at":"2030-01-02T06:30:00Z","repeat":[0,2],"enabled":true,"status":"scheduled"}""")
        val made = api.addAlarm("Gym", "06:30", listOf(0, 2), null, 120)
        assertEquals(listOf(0, 2), made.repeat)
        val add = server.takeRequest()
        assertEquals("POST", add.method); assertEquals("/hub/planner/alarms", add.path)
        val body = Json.parseToJsonElement(add.body.readUtf8()).jsonObject
        assertEquals("06:30", body["time"]!!.jsonPrimitive.content)
        assertEquals("[0,2]", body["repeat"].toString()); assertEquals("120", body["volume"]!!.jsonPrimitive.content)
        assertEquals("null", body["station_id"].toString())  // an explicit chime

        ok("""{"id":"a1","label":"Gym","due_at":"2030-01-02T06:30:00Z","enabled":false,"status":"scheduled"}""")
        assertFalse(api.setAlarmEnabled("a1", false).enabled)
        val off = server.takeRequest()
        assertEquals("PATCH", off.method); assertEquals("/hub/planner/alarms/a1", off.path)
        assertEquals("""{"enabled":false}""", off.body.readUtf8())

        ok("""{"id":"a1","label":"Run","due_at":"2030-01-02T07:15:00Z","status":"scheduled"}""")
        assertEquals("Run", api.updateAlarm("a1", "Run", "07:15", emptyList(), "s1", 100).label)
        assertEquals("PATCH", server.takeRequest().method)

        ok("""{}""")
        api.deleteAlarm("a1")
        assertEquals("DELETE", server.takeRequest().method)
        ok("""[{"id":"a1","label":"Gym","due_at":"2030-01-02T06:30:00Z","repeat":[1]}]""")
        assertEquals(listOf(1), api.alarms().single().repeat)
        Unit
    }

    @Test fun `a meeting is renamed by the owner or written again from the transcript`() = runBlocking {
        ok("""{"id":"m1","title":"Metrics store decision","description":"ClickHouse versus InfluxDB.","title_source":"owner"}""")
        val renamed = api.renameMeeting("m1", "Metrics store decision", "ClickHouse versus InfluxDB.")
        assertEquals("owner", renamed.titleSource); assertEquals("ClickHouse versus InfluxDB.", renamed.description)
        val put = server.takeRequest()
        assertEquals("PUT", put.method); assertEquals("/hub/meetings/m1/title", put.path)
        val body = Json.parseToJsonElement(put.body.readUtf8()).jsonObject
        assertEquals("Metrics store decision", body["title"]!!.jsonPrimitive.content)
        assertEquals("ClickHouse versus InfluxDB.", body["description"]!!.jsonPrimitive.content)

        ok("""{"id":"m1","title":"Written Again","description":"Fresh.","title_source":"generated"}""")
        assertEquals("generated", api.describeMeeting("m1").titleSource)
        val post = server.takeRequest()
        assertEquals("POST", post.method); assertEquals("/hub/meetings/m1/describe", post.path)
        assertEquals("local", Json.parseToJsonElement(post.body.readUtf8()).jsonObject["model"]!!.jsonPrimitive.content)
        Unit
    }

    @Test fun `saved chats are listed, opened and deleted for the owner`() = runBlocking {
        ok("""[{"id":"c1","title":"Newest","updated_at":"2026-10-07T10:00:00Z"},{"id":"c2","title":"Older"}]""")
        assertEquals(listOf("Newest", "Older"), api.chats("owner").map { it.title })
        val list = server.takeRequest()
        assertEquals("GET", list.method); assertEquals("/hub/chats?user_id=owner", list.path)

        ok("""{"id":"c1","title":"Newest","turns":[{"text":"hi","reply":"hello","status":"complete"},{"text":"lost","reply":null,"status":"unknown"}]}""")
        val detail = api.chat("owner", "c1")
        assertEquals(2, detail.turns.size)
        assertEquals("/hub/chats/c1?user_id=owner", server.takeRequest().path)

        ok("""{"deleted":true}""")
        api.deleteChat("owner", "c1")
        val delete = server.takeRequest()
        assertEquals("DELETE", delete.method); assertEquals("/hub/chats/c1?user_id=owner", delete.path)
        assertEquals("1", delete.getHeader("X-Reachy-CSRF"))
        Unit
    }

    @Test fun `typed turns join the chat record and spoken turns do not`() = runBlocking {
        ok("""{"reply":"hi","session_id":"s"}""")
        assertEquals("hi", api.send("owner", "hello", spoken = false, chatId = "c1").reply)
        val typed = Json.parseToJsonElement(server.takeRequest().body.readUtf8()).jsonObject
        assertEquals("text", typed["input_modality"]!!.jsonPrimitive.content)
        assertEquals("c1", typed["chat_id"]!!.jsonPrimitive.content)
        assertEquals("web", typed["channel"]!!.jsonPrimitive.content)

        ok("""{"reply":"ok"}""")
        api.send("owner", "add a task", spoken = true, chatId = "c1")
        val spoken = Json.parseToJsonElement(server.takeRequest().body.readUtf8()).jsonObject
        assertEquals("voice", spoken["input_modality"]!!.jsonPrimitive.content)
        assertNull(spoken["chat_id"])
    }

    @Test fun `an expired session surfaces as unauthorized and server detail is reported`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Authentication required"}"""))
        try { api.tasks(); fail() } catch (e: ApiException) { assertTrue(e.unauthorized); assertEquals("Authentication required", e.message) }
    }

    @Test fun `tasks parse and completing a task posts to the complete route`() = runBlocking {
        ok("""[{"id":"t1","text":"milk","status":"open","created_at":"2026-10-07T00:00:00Z"},{"id":"t2","text":"x","status":"done"}]""")
        val tasks = api.tasks()
        assertEquals(listOf(false, true), tasks.map { it.done })
        server.takeRequest()
        ok("{}")
        api.setTaskDone("t1", true)
        val request = server.takeRequest()
        assertEquals("POST", request.method); assertEquals("/hub/planner/tasks/t1/complete", request.path)
    }

    @Test fun `meeting upload sends the title and the audio part`() = runBlocking {
        ok("""{"id":"m1","title":"Standup","status":"uploaded"}""")
        val file = File.createTempFile("meeting", ".m4a").apply { writeBytes(byteArrayOf(1, 2, 3)) }
        assertEquals("m1", api.uploadMeeting("Standup", file).id)
        val body = server.takeRequest().body.readUtf8()
        assertTrue(body.contains("name=\"title\"")); assertTrue(body.contains("filename=\"${file.name}\""))
        assertFalse(body.isEmpty()); file.delete(); Unit
    }

    @Test fun `meeting detail parses transcript and speaker segments`() = runBlocking {
        ok("""{"id":"m","title":"T","status":"complete","transcript_segments":[{"start":1.0,"end":2.0,"text":"hello"}],"diarization_segments":[{"start":0.0,"end":5.0,"speaker":"SPEAKER_00"}]}""")
        val meeting = api.meeting("m")
        assertEquals("hello", meeting.transcript!!.single().text)
        assertEquals("SPEAKER_00", app.reachy.companion.data.speakerFor(meeting, meeting.transcript!!.single()))
    }

    @Test fun `speaker naming sends only the changed label and parses the updated meeting`() = runBlocking {
        ok("""{"id":"m","title":"T","status":"complete","speaker_names":{"SPEAKER_00":"Priya"}}""")
        val meeting = api.setSpeakerNames("m", mapOf("SPEAKER_00" to "Priya"))
        val request = server.takeRequest()
        assertEquals("PUT", request.method); assertEquals("/hub/meetings/m/speakers", request.path)
        assertEquals("Priya", Json.parseToJsonElement(request.body.readUtf8()).jsonObject["names"]!!.jsonObject["SPEAKER_00"]!!.jsonPrimitive.content)
        assertEquals("Priya", meeting.speakerNames["SPEAKER_00"])
    }

    @Test fun `suggestions parse and applying or restoring a correction uses the segment routes`() = runBlocking {
        ok("""{"suggestions":[{"segment":0,"original":"Germanite","suggested":"Gemini","reason":"AI model","corrected_text":"try Gemini"}],"checked_segments":2,"truncated":false}""")
        val result = api.suggestCorrections("m", "cloud")
        val request = server.takeRequest()
        assertEquals("/hub/meetings/m/corrections/suggest", request.path)
        assertEquals("cloud", Json.parseToJsonElement(request.body.readUtf8()).jsonObject["model"]!!.jsonPrimitive.content)
        assertEquals("Gemini", result.suggestions.single().suggested)

        ok("""{"id":"m","title":"T","transcript_corrections":{"0":"try Gemini"}}""")
        assertEquals("try Gemini", api.setCorrection("m", 0, "try Gemini").corrections["0"])
        assertEquals("PUT", server.takeRequest().method)
        ok("""{"id":"m","title":"T"}""")
        api.clearCorrection("m", 0)
        val clear = server.takeRequest()
        assertEquals("DELETE", clear.method); assertEquals("/hub/meetings/m/corrections/0", clear.path)
    }

    @Test fun `a server refusal such as no local model is reported with its detail`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(409).setBody("""{"detail":"suggestions need a local language model to be configured"}"""))
        try { api.suggestCorrections("m", "local"); fail() } catch (e: ApiException) { assertEquals(409, e.code); assertTrue(e.message!!.contains("local language model")) }
    }

    @Test fun `change everywhere posts find and replace and returns the count`() = runBlocking {
        ok("""{"meeting":{"id":"m","title":"T","transcript_corrections":{"0":"a Gemini"}},"replaced_segments":2}""")
        val result = api.replaceEverywhere("m", "Germanite", "Gemini")
        val request = server.takeRequest()
        assertEquals("/hub/meetings/m/corrections/replace", request.path)
        val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
        assertEquals("Germanite", body["find"]!!.jsonPrimitive.content); assertEquals("Gemini", body["replace"]!!.jsonPrimitive.content)
        assertEquals(2, result.replacedSegments)
    }

    @Test fun `key terms and the glossary use their own routes`() = runBlocking {
        ok("""{"id":"m","title":"T","key_terms":["Gemini","Codex"]}""")
        assertEquals(listOf("Gemini", "Codex"), api.setKeyTerms("m", listOf("Gemini", "Codex")).keyTerms)
        val put = server.takeRequest()
        assertEquals("PUT", put.method); assertEquals("/hub/meetings/m/terms", put.path)
        ok("""["ClickHouse","Gemini"]""")
        assertEquals(listOf("ClickHouse", "Gemini"), api.glossary())
        ok("""["ClickHouse","Gemini","Claude Code"]""")
        api.addGlossaryTerm("Claude Code")
        server.takeRequest(); val post = server.takeRequest()
        assertEquals("POST", post.method); assertEquals("/hub/meeting-terms", post.path)
        ok("""["Gemini"]""")
        api.deleteGlossaryTerm("Click House & co")
        val delete = server.takeRequest()
        assertEquals("DELETE", delete.method); assertEquals("/hub/meeting-terms?term=Click%20House%20%26%20co", delete.path)
    }

    @Test fun `suggestions carry confidence and source`() = runBlocking {
        ok("""{"suggestions":[{"segment":1,"original":"germanite","suggested":"Gemini","reason":"r","corrected_text":"And Gemini.","confidence":"high","source":"terms"}],"checked_segments":5,"truncated":false,"terms_used":4,"candidates_checked":3}""")
        val result = api.suggestCorrections("m", "local")
        assertEquals("high", result.suggestions.single().confidence); assertEquals(4, result.termsUsed)
    }

    @Test fun `deep review routes and the finished-job helper`() = runBlocking {
        ok("""{"configured":true,"available":false,"reason":"the model manager is failed","eta_seconds":330}""")
        val info = api.deepInfo()
        assertEquals("/hub/deep-review/info", server.takeRequest().path)
        assertTrue(info.configured && !info.available); assertEquals("the model manager is failed", info.reason)

        ok("""{"id":"j1","meeting_id":"m1","meeting_title":"Sync","status":"switching","stage":"Loading","reachy_unavailable":false,"reachy_online":false,"eta_seconds":330}""")
        val job = api.startDeepReview("m1")
        val started = server.takeRequest()
        assertEquals("POST", started.method); assertEquals("/hub/meetings/m1/corrections/deep-review", started.path)
        assertFalse(job.finished)

        ok("""{"id":"j1","meeting_id":"m1","meeting_title":"Sync","status":"done","stage":"Reachy is back online","reachy_unavailable":false,"reachy_online":true,"result":{"suggestions":[{"segment":1,"original":"germanite","suggested":"Gemini","reason":"r","corrected_text":"And Gemini.","confidence":"likely","source":"terms"}],"checked_segments":2,"terms_used":4}}""")
        val done = api.deepJob("j1")
        assertTrue(done.finished && done.reachyOnline)
        assertEquals("Gemini", done.result!!.suggestions.single().suggested)
    }

    @Test fun `no review yet is a null body not an error`() = runBlocking {
        ok("null")
        assertNull(api.deepCurrent())
        ok("""{"id":"j2","meeting_id":"m","status":"reviewing"}""")
        assertEquals("reviewing", api.deepCurrent()!!.status)
    }

    @Test fun `deleting cancelling and clearing outputs use their own routes`() = runBlocking {
        ok("""{"deleted":true}""")
        api.deleteMeeting("m1")
        val delete = server.takeRequest()
        assertEquals("DELETE", delete.method); assertEquals("/hub/meetings/m1", delete.path)
        ok("""{"id":"m1","title":"T","status":"cancelled"}""")
        assertEquals("cancelled", api.cancelMeeting("m1").status)
        assertEquals("/hub/meetings/m1/cancel", server.takeRequest().path)
        ok("""{"id":"m1","title":"T"}""")
        api.clearOutput("m1", "summary")
        val clear = server.takeRequest()
        assertEquals("DELETE", clear.method); assertEquals("/hub/meetings/m1/outputs/summary", clear.path)
    }

    @Test fun `summary and minutes carry the model and a rerun can pick another tier`() = runBlocking {
        ok("""{"id":"m1","title":"T","status":"aligning","summary":{"text":"About ClickHouse.","tier":"local","generated_at":"2026-10-07T10:00:00Z"}}""")
        val local = api.generateOutput("m1", "summary", "local")
        val request = server.takeRequest()
        assertEquals("/hub/meetings/m1/outputs/summary", request.path)
        assertEquals("local", Json.parseToJsonElement(request.body.readUtf8()).jsonObject["model"]!!.jsonPrimitive.content)
        assertEquals("local", local.summary!!.tier)
        ok("""{"id":"m1","title":"T","minutes":{"text":"Decisions","tier":"cloud","generated_at":"2026-10-07T10:05:00Z"}}""")
        assertEquals("cloud", api.generateOutput("m1", "minutes", "cloud").minutes!!.tier)
        assertEquals("cloud", Json.parseToJsonElement(server.takeRequest().body.readUtf8()).jsonObject["model"]!!.jsonPrimitive.content)
        ok("""{"id":"j","meeting_id":"m1","task":"minutes","status":"switching"}""")
        assertEquals("minutes", api.startDeepOutput("m1", "minutes").task)
        assertEquals("/hub/meetings/m1/outputs/minutes/deep", server.takeRequest().path)
    }

    @Test fun `an attached meeting is sent as context and the answer says which meeting it used`() = runBlocking {
        ok("""{"reply":"ClickHouse is a column-oriented database.","context_meeting":"Database choice"}""")
        val reply = api.send("owner", "what is clickhouse", spoken = false, chatId = "c1", contextMeetingId = "m1")
        val body = Json.parseToJsonElement(server.takeRequest().body.readUtf8()).jsonObject
        assertEquals("m1", body["context_meeting_id"]!!.jsonPrimitive.content)
        assertEquals("Database choice", reply.contextMeeting)
        ok("""{"reply":"plain"}""")
        api.send("owner", "hello", spoken = false, chatId = null)
        assertNull(Json.parseToJsonElement(server.takeRequest().body.readUtf8()).jsonObject["context_meeting_id"])
    }

    @Test fun `asking the cloud about a meeting sets force_frontier only when chosen`() = runBlocking {
        ok("""{"reply":"x"}""")
        api.send("owner", "q", spoken = false, chatId = null, contextMeetingId = "m1")
        assertNull(Json.parseToJsonElement(server.takeRequest().body.readUtf8()).jsonObject["force_frontier"])
        ok("""{"reply":"x"}""")
        api.send("owner", "q", spoken = false, chatId = null, contextMeetingId = "m1", forceFrontier = true)
        assertEquals("true", Json.parseToJsonElement(server.takeRequest().body.readUtf8()).jsonObject["force_frontier"]!!.jsonPrimitive.content)
    }

    @Test fun `a reply carries the web sources it was grounded on`() = runBlocking {
        ok("""{"reply":"Open source [S1].","web_search":{"query":"is clickhouse free","failed":false,"results":[{"title":"FAQ","url":"https://clickhouse.com/docs/faq","snippet":"Apache","source_domain":"clickhouse.com"}]}}""")
        val reply = api.send("owner", "is clickhouse free?", spoken = false, chatId = null)
        assertEquals("clickhouse.com", reply.webSearch!!.results.single().sourceDomain)
        ok("""{"reply":"no search"}""")
        assertNull(api.send("owner", "hi", spoken = false, chatId = null).webSearch)
    }

    @Test fun `home reads the snapshot or one section, and the brief is a POST with the CSRF header`() = runBlocking {
        ok("""{"generated_at":"x","sources":{"tasks":"ok"},"tasks":{"status":"ok","total":1,"shown":1,"items":[{"id":"t","text":"A","ref":{"screen":"tasks"}}]}}""")
        assertEquals(1, api.home().tasks!!.total)
        val all = server.takeRequest()
        assertEquals("GET", all.method); assertEquals("/hub/home", all.path); assertEquals("1", all.getHeader("X-Reachy-CSRF"))

        ok("""{"generated_at":"y","sources":{"reminders":"empty"},"reminders":{"status":"empty"}}""")
        assertEquals("empty", api.home(listOf("reminders")).reminders!!.status)
        assertEquals("/hub/home?sections=reminders", server.takeRequest().path)

        ok("""{"mode":"generated","text":"-","narrative":"Hello.","model":"m","lines":[]}""")
        assertEquals("Hello.", api.homeBrief(true).narrative)
        val brief = server.takeRequest()
        assertEquals("POST", brief.method); assertEquals("/hub/home/brief", brief.path); assertEquals("1", brief.getHeader("X-Reachy-CSRF"))
        assertEquals("true", Json.parseToJsonElement(brief.body.readUtf8()).jsonObject["narrative"]!!.jsonPrimitive.content)
    }

    @Test fun `home turns a refusal into an ApiException the screen can word`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Login required"}"""))
        try { api.home(); fail("expected a refusal") } catch (e: ApiException) { assertTrue(e.unauthorized) }
        server.enqueue(MockResponse().setResponseCode(502).setBody("""{"detail":"Home unavailable"}"""))
        try { api.home(); fail("expected a failure") } catch (e: ApiException) { assertEquals(502, e.code); assertEquals("Home unavailable", e.message) }
    }
}
