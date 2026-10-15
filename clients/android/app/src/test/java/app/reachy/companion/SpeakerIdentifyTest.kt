package app.reachy.companion

import app.reachy.companion.data.Choice
import app.reachy.companion.data.IdentifyScreen
import app.reachy.companion.data.Meeting
import app.reachy.companion.data.Mode
import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.ReachyApi
import app.reachy.companion.data.SamplePool
import app.reachy.companion.data.SpeakerCard
import app.reachy.companion.data.SpeakerDecision
import app.reachy.companion.data.SpeakerIdentityRecord
import app.reachy.companion.data.SpeakerSample
import app.reachy.companion.data.decisionsFor
import app.reachy.companion.data.initialChoice
import app.reachy.companion.data.outputIsStale
import app.reachy.companion.data.poolOf
import app.reachy.companion.data.rangeFinished
import app.reachy.companion.data.sampleLabel
import app.reachy.companion.data.speakerReviewNeeded
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
import org.junit.Before
import org.junit.Test

class SpeakerIdentifyTest {
    private fun sample(start: Double, end: Double = start + 6) = SpeakerSample(start, end, text = "t$start")
    private val one = SpeakerCard("SPEAKER_00", "Speaker 1", samples = listOf(sample(1.0), sample(20.0)), alternates = listOf(sample(40.0)))
    private val two = SpeakerCard("SPEAKER_01", "Speaker 2", samples = listOf(sample(10.0)))
    private val named = SpeakerCard("SPEAKER_02", "Priya", samples = listOf(sample(5.0)), identity = SpeakerIdentityRecord("named", "Priya"))
    private val unknown = SpeakerCard("SPEAKER_03", "Speaker 4", identity = SpeakerIdentityRecord("unknown"))

    private fun choices(vararg pairs: Pair<SpeakerCard, Choice>) = listOf(one, two, named, unknown).associate { it.label to initialChoice(it) } + pairs.associate { it.first.label to it.second }

    @Test fun `nothing is sent for a speaker the owner left alone`() {
        assertEquals(emptyMap<String, SpeakerDecision>(), decisionsFor(listOf(one, two, named, unknown), choices()))
    }

    @Test fun `a name, Unknown and Skip are decisions and a name is trimmed`() {
        val decisions = decisionsFor(listOf(one, two), choices(one to Choice(Mode.NAME, "  Priya Shah "), two to Choice(Mode.UNKNOWN)))
        assertEquals(mapOf("SPEAKER_00" to SpeakerDecision("named", "Priya Shah"), "SPEAKER_01" to SpeakerDecision("unknown")), decisions)
        assertEquals(SpeakerDecision("skipped"), decisionsFor(listOf(two), choices(two to Choice(Mode.SKIPPED)))["SPEAKER_01"])
    }

    @Test fun `removing a saved name or decision clears it and an empty name on an unsaved speaker is nothing`() {
        val cards = listOf(one, named, unknown)
        val decisions = decisionsFor(cards, choices(named to Choice(), unknown to Choice(Mode.NAME, "  ")))
        assertEquals(mapOf("SPEAKER_02" to SpeakerDecision("clear"), "SPEAKER_03" to SpeakerDecision("clear")), decisions)
        assertEquals(emptyMap<String, SpeakerDecision>(), decisionsFor(listOf(one), choices(one to Choice(Mode.NAME, " "))))
    }

    @Test fun `renaming a saved speaker and going back to the saved value`() {
        assertEquals(SpeakerDecision("named", "Priya S."), decisionsFor(listOf(named), choices(named to Choice(Mode.NAME, "Priya S.")))["SPEAKER_02"])
        assertTrue(decisionsFor(listOf(named), choices(named to Choice(Mode.NAME, " Priya "))).isEmpty())
        assertEquals(SpeakerDecision("unknown"), decisionsFor(listOf(named), choices(named to Choice(Mode.UNKNOWN)))["SPEAKER_02"])
    }

    @Test fun `another sample swaps one in, cycles through every spare and never loses a sample`() {
        var pool = poolOf(one)
        val first = pool.shown[0]
        pool = pool.another(first)
        assertEquals(listOf(sample(40.0), sample(20.0)), pool.shown)
        assertEquals(listOf(first), pool.spare)
        pool = pool.another(pool.shown[0])
        assertEquals(first, pool.shown[0])
        assertEquals(setOf(sample(1.0), sample(20.0), sample(40.0)), (pool.shown + pool.spare).toSet())
        val none = SamplePool(listOf(sample(1.0)), emptyList())
        assertEquals(none, none.another(sample(1.0)))
    }

    @Test fun `a sample stops by itself at its end and a normal playback never does`() {
        assertFalse(rangeFinished(6999, 7000)); assertTrue(rangeFinished(7000, 7000)); assertTrue(rangeFinished(7400, 7000))
        assertFalse(rangeFinished(900000, -1))
        assertEquals("0:01–0:07", sampleLabel(sample(1.0, 7.0))); assertEquals("1:05–1:13", sampleLabel(sample(65.2, 73.9)))
    }

    @Test fun `the screen and the meeting parse what the hub sends and ignore what they do not know`() {
        val json = Json { ignoreUnknownKeys = true }
        val screen = json.decodeFromString<IdentifyScreen>(
            """{"meeting_id":"m","fingerprint":"fp","needs_review":true,"suggestions":["Dana Lee"],"future":1,
               "superseded":{"identities":{"SPEAKER_00":{"status":"named","name":"Priya","contact_id":null}},"superseded_at":"x"},
               "speakers":[{"label":"SPEAKER_00","display_name":"Speaker 1","seconds":12.5,"lines":3,"reason":null,"identity":null,
                 "samples":[{"start":1.0,"end":7.0,"quality":"low","notes":["short"],"text":"hi"}],"alternates":[]}]}""",
        )
        assertEquals("fp", screen.fingerprint); assertTrue(screen.needsReview); assertEquals("low", screen.speakers[0].samples[0].quality)
        assertEquals("Priya", screen.superseded!!.identities["SPEAKER_00"]!!.name)
        val meeting = json.decodeFromString<Meeting>("""{"id":"m","title":"T","stale_outputs":["summary"],"speaker_identity":{"fingerprint":"fp","identities":{},"superseded":{"identities":{"A":{"status":"unknown"}}}}}""")
        assertTrue(meeting.outputIsStale("summary")); assertFalse(meeting.outputIsStale("minutes")); assertTrue(meeting.speakerReviewNeeded)
        val plain = json.decodeFromString<Meeting>("""{"id":"m","title":"T"}""")
        assertFalse(plain.speakerReviewNeeded); assertTrue(plain.staleOutputs.isEmpty())
        assertNull(plain.speakerIdentity.superseded)
    }
}

class SpeakerIdentifyApiTest {
    private lateinit var server: MockWebServer
    private var stored: String? = null
    private lateinit var api: ReachyApi

    @Before fun setUp() {
        server = MockWebServer().apply { start() }
        api = ReachyApi(server.url("/hub").toString(), PersistentCookieJar({ stored }, { stored = it }))
    }

    @After fun tearDown() = server.shutdown()

    @Test fun `the screen is read from and decisions are saved to the hub in one request with the CSRF header and the fingerprint`() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"meeting_id":"m1","fingerprint":"fp1","speakers":[]}""").setHeader("Content-Type", "application/json"))
        assertEquals("fp1", api.identifySpeakers("m1").fingerprint)
        val get = server.takeRequest()
        assertEquals("GET", get.method); assertEquals("/hub/meetings/m1/speakers/identify", get.path)

        server.enqueue(MockResponse().setBody("""{"id":"m1","title":"T","speaker_names":{"SPEAKER_00":"Priya"}}""").setHeader("Content-Type", "application/json"))
        val saved = api.confirmSpeakers("m1", "fp1", linkedMapOf("SPEAKER_00" to SpeakerDecision("named", "Priya"), "SPEAKER_01" to SpeakerDecision("unknown"), "SPEAKER_02" to SpeakerDecision("clear")))
        assertEquals(mapOf("SPEAKER_00" to "Priya"), saved.speakerNames)
        val put = server.takeRequest()
        assertEquals("PUT", put.method); assertEquals("/hub/meetings/m1/speakers/identify", put.path); assertEquals("1", put.getHeader("X-Reachy-CSRF"))
        val body = Json.parseToJsonElement(put.body.readUtf8()).jsonObject
        assertEquals("fp1", body["fingerprint"]!!.jsonPrimitive.content)
        val decisions = body["decisions"]!!.jsonObject
        assertEquals("named", decisions["SPEAKER_00"]!!.jsonObject["status"]!!.jsonPrimitive.content)
        assertEquals("Priya", decisions["SPEAKER_00"]!!.jsonObject["name"]!!.jsonPrimitive.content)
        assertEquals(false, decisions["SPEAKER_01"]!!.jsonObject.containsKey("name"))  // Unknown never carries a name
        assertEquals("clear", decisions["SPEAKER_02"]!!.jsonObject["status"]!!.jsonPrimitive.content)
    }

    @Test fun `a changed speaker detection is reported with the hub's own message`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(409).setBody("""{"detail":"the speaker detection changed since you opened this screen; reload it"}""").setHeader("Content-Type", "application/json"))
        try { api.confirmSpeakers("m1", "stale", mapOf("SPEAKER_00" to SpeakerDecision("unknown"))); org.junit.Assert.fail() } catch (e: app.reachy.companion.data.ApiException) {
            assertEquals(409, e.code); assertTrue(e.message!!.contains("speaker detection changed"))
        }
    }
}
