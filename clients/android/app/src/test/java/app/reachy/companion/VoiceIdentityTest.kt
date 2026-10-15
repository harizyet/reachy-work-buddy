package app.reachy.companion

import app.reachy.companion.data.ApiException
import app.reachy.companion.data.BenchmarkClip
import app.reachy.companion.data.ClientIdentity
import app.reachy.companion.data.Endpointer
import app.reachy.companion.data.FRAME_SAMPLES
import app.reachy.companion.data.GV_PLAN
import app.reachy.companion.data.MatchKind
import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.ReachyApi
import app.reachy.companion.data.VoiceIdentityModel
import app.reachy.companion.data.VoiceStateView
import app.reachy.companion.data.Wav
import app.reachy.companion.data.cleanAlias
import app.reachy.companion.data.currentMatch
import app.reachy.companion.data.frameDbfs
import app.reachy.companion.data.gvComplete
import app.reachy.companion.data.gvCounts
import app.reachy.companion.data.gvLabel
import app.reachy.companion.data.ownerMatch
import app.reachy.companion.data.provenanceHeaders
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class VoiceIdentityLogicTest {
    @Test fun `a WAV is a canonical 16 kHz mono PCM16 file`() {
        val wav = Wav.encode(shortArrayOf(1, -2, 300))
        assertEquals("RIFF", String(wav, 0, 4)); assertEquals("WAVE", String(wav, 8, 4)); assertEquals("data", String(wav, 36, 4))
        fun int(at: Int) = (wav[at].toInt() and 0xFF) or ((wav[at + 1].toInt() and 0xFF) shl 8) or ((wav[at + 2].toInt() and 0xFF) shl 16) or ((wav[at + 3].toInt() and 0xFF) shl 24)
        assertEquals(16000, int(24)); assertEquals(32000, int(28)); assertEquals(6, int(40)); assertEquals(42, int(4))
        assertEquals(1, wav[22].toInt()); assertEquals(16, wav[34].toInt()); assertEquals(50, wav.size)
        assertEquals(-2, ((wav[47].toInt() shl 8) or (wav[46].toInt() and 0xFF)).toShort().toInt())
    }

    @Test fun `frame level is in dBFS`() {
        assertTrue(frameDbfs(ShortArray(FRAME_SAMPLES)) < -100f)
        assertEquals(-6f, frameDbfs(ShortArray(FRAME_SAMPLES) { 16384 }), 0.2f)
    }

    private fun feed(e: Endpointer, vararg parts: Pair<Int, Float>): Endpointer.Event {
        var last = Endpointer.Event.Waiting
        for ((count, level) in parts) repeat(count) {
            if (last != Endpointer.Event.Ended && last != Endpointer.Event.NoSpeech && last != Endpointer.Event.TooLong) last = e.feed(level)
        }
        return last
    }

    @Test fun `an utterance ends after a second of quiet and keeps a short lead-in`() {
        val e = Endpointer()
        assertEquals(Endpointer.Event.Ended, feed(e, 20 to -60f, 40 to -20f, 40 to -60f))
        assertEquals(20, e.firstSpeechFrame)
        assertEquals(10 * FRAME_SAMPLES, e.keepFrom())
    }

    @Test fun `silence alone times out as no speech`() {
        assertEquals(Endpointer.Event.NoSpeech, feed(Endpointer(), 400 to -70f))
    }

    @Test fun `a click is not a sentence and speech after it is still heard`() {
        val e = Endpointer()
        assertEquals(Endpointer.Event.Waiting, feed(e, 20 to -60f, 3 to -10f, 20 to -60f))   // too short to start
        assertEquals(Endpointer.Event.Ended, feed(e, 30 to -20f, 40 to -60f))
    }

    @Test fun `a steady noisy room is not mistaken for speech`() {
        val e = Endpointer()
        assertEquals(Endpointer.Event.NoSpeech, feed(e, 400 to -35f))   // the threshold follows the floor
        assertEquals(Endpointer.Event.Ended, feed(Endpointer(), 20 to -35f, 40 to -15f, 40 to -35f))
    }

    @Test fun `very long speech is cut off`() {
        assertEquals(Endpointer.Event.TooLong, feed(Endpointer(), 10 to -60f, 900 to -20f))
    }

    @Test fun `until calibration is approved nothing is ever shown as verified`() {
        for (state in listOf("verified", "uncertain", "not_verified", "unavailable")) {
            val shown = ownerMatch(VoiceStateView(state, reasons = if (state == "unavailable") listOf("not_calibrated") else emptyList()), calibrated = false)
            assertFalse(state, shown.kind == MatchKind.Verified)
            assertTrue(state, shown.kind in listOf(MatchKind.Unverified, MatchKind.Inconclusive))
        }
        assertEquals(MatchKind.Unverified, ownerMatch(VoiceStateView("verified"), calibrated = false).kind)
        assertEquals(MatchKind.Inconclusive, ownerMatch(VoiceStateView("uncertain", reasons = listOf("too_quiet")), calibrated = false).kind)
    }

    @Test fun `once calibrated each state has its own plain wording and none mentions permissions`() {
        assertEquals("Owner voice verified", ownerMatch(VoiceStateView("verified"), true).label)
        assertEquals(MatchKind.NotVerified, ownerMatch(VoiceStateView("not_verified"), true).kind)
        assertEquals(MatchKind.Inconclusive, ownerMatch(VoiceStateView("uncertain"), true).kind)
        assertEquals(MatchKind.NoProfile, ownerMatch(VoiceStateView("unavailable", reasons = listOf("no_profile")), true).kind)
        assertEquals(MatchKind.Unavailable, ownerMatch(VoiceStateView("unavailable", reasons = listOf("service_unavailable")), true).kind)
        for (state in listOf("verified", "uncertain", "not_verified", "unavailable")) {
            val text = ownerMatch(VoiceStateView(state), true).let { "${it.label} ${it.detail}".lowercase() }
            assertFalse(text, "unlock" in text || "allow" in text || "permission" in text || "access" in text)
        }
    }

    @Test fun `a result is shown only while it is current`() {
        val view = VoiceStateView("verified", expiresInSeconds = 10.0)
        assertNotNull(currentMatch(view, 1_000, 10_999))
        assertNull(currentMatch(view, 1_000, 11_000))
        assertNull(currentMatch(null, 0, 0))
    }

    @Test fun `provenance headers carry the install and a cleaned device name`() {
        val h = provenanceHeaders("install-1", "Phone 9 <script>", "utt-1")
        assertEquals("android", h["X-Reachy-Client-Kind"]); assertEquals("install-1", h["X-Reachy-Client-Id"])
        assertEquals("Phone 9 script", h["X-Reachy-Device-Id"]); assertEquals("utt-1", h["X-Reachy-Utterance-Id"])
        assertFalse(provenanceHeaders("i", "")["X-Reachy-Device-Id"] != null)
        assertEquals(64, provenanceHeaders("x".repeat(100), "d")["X-Reachy-Client-Id"]!!.length)
    }

    @Test fun `every evaluation label fits the hub's label format and attacks never claim to be someone else`() {
        val format = Regex("^role=(enroll|trial);speaker=[A-Za-z0-9_-]{1,32};condition=[A-Za-z0-9_-]{1,32}$")
        for (step in GV_PLAN) assertTrue(gvLabel(step), format.matches(gvLabel(step)))
        assertEquals("role=trial;speaker=JaneD;condition=other_person", gvLabel(GV_PLAN.first { it.nonOwner }, "Jane D!"))
        assertEquals("person1", cleanAlias("   "))
        assertEquals(setOf("replay", "synthetic"), GV_PLAN.filter { it.attack }.map { it.condition }.toSet())
        assertTrue(GV_PLAN.first { it.id == "enroll" }.role == "enroll" && GV_PLAN.filter { it.id != "enroll" }.all { it.role == "trial" })
        assertTrue(GV_PLAN.any { it.condition == "held_out" } && GV_PLAN.any { it.nonOwner })
    }

    @Test fun `evaluation progress counts clips by condition`() {
        val clips = listOf("quiet", "quiet", "replay").map { BenchmarkClip("s", "role=trial;speaker=owner;condition=$it") } + BenchmarkClip("u", null)
        assertEquals(mapOf("quiet" to 2, "replay" to 1), gvCounts(clips))
        assertFalse(gvComplete(gvCounts(clips)))
        assertTrue(gvComplete(GV_PLAN.associate { it.condition to it.target }))
    }
}

class VoiceIdentityModelTest {
    private lateinit var server: MockWebServer
    private var stored: String? = null
    private var phoneRecognizer = false
    private var clock = 1_000L
    // Unconfined: the model's coroutine starts on this thread; its network call finishes on an IO thread, so each test waits for `busy` to clear.
    private val scope = CoroutineScope(Dispatchers.Unconfined)
    private lateinit var model: VoiceIdentityModel
    private val wav = Wav.encode(shortArrayOf(1, 2, 3))

    @Before fun setUp() {
        server = MockWebServer().apply { start() }
        val api = ReachyApi(server.url("/hub").toString(), PersistentCookieJar({ stored }, { stored = it }))
        model = VoiceIdentityModel(scope, { api }, { ClientIdentity("install-1", "Phone") }, { phoneRecognizer }, { clock })
    }

    @After fun tearDown() = server.shutdown()

    private fun until(what: () -> Boolean) { val end = System.currentTimeMillis() + 5000; while (!what() && System.currentTimeMillis() < end) Thread.sleep(5); assertTrue("timed out", what()) }
    private fun settle() { Thread.sleep(20); until { !model.busy } }
    private fun json(body: String, code: Int = 200) = server.enqueue(MockResponse().setResponseCode(code).setBody(body).setHeader("Content-Type", "application/json"))
    private val enabledStatus = """{"enabled":true,"ready":true,"profile":null,"draft":{"samples":[],"usable_samples":0,"required_samples":5},"reauthenticated":false,"calibrated":false}"""

    @Test fun `hub capture is used only when the hub has the feature on and the owner has not chosen the phone's recogniser`() = runBlocking {
        assertFalse(model.hubCapture)
        json(enabledStatus); model.refresh(); until { model.status != null }
        assertTrue(model.hubCapture)
        phoneRecognizer = true
        assertFalse(model.hubCapture)
        phoneRecognizer = false
        json("""{"enabled":false}"""); model.refresh(); until { model.status?.enabled == false }
        assertFalse(model.hubCapture)
    }

    @Test fun `an enrolment clip goes up once as a raw WAV with its provenance and no other copy`() = runBlocking {
        json("""{"sample_id":"s1","quality_ok":true,"reasons":[],"speech_seconds":2.5}"""); json(enabledStatus)
        model.addSample(wav); settle()
        val upload = server.takeRequest()
        assertEquals("/hub/voice-identity/enrollment/samples", upload.path)
        assertEquals("audio/wav", upload.getHeader("Content-Type")); assertEquals("1", upload.getHeader("X-Reachy-CSRF"))
        assertEquals("android", upload.getHeader("X-Reachy-Client-Kind")); assertEquals("install-1", upload.getHeader("X-Reachy-Client-Id")); assertEquals("Phone", upload.getHeader("X-Reachy-Device-Id"))
        assertEquals(wav.toList(), upload.body.readByteArray().toList())
        assertEquals("/hub/voice-identity/status", server.takeRequest().path)
        assertEquals("Clip added.", model.message)
    }

    @Test fun `an unusable clip says why and is not counted`() = runBlocking {
        json("""{"sample_id":"s2","quality_ok":false,"reasons":["too_quiet"],"speech_seconds":0.4}"""); json(enabledStatus)
        model.addSample(wav); settle()
        assertTrue(model.message!!.contains("Too quiet"))
    }

    @Test fun `saving needs the consent box and re-asks for the password before the hub is told`() = runBlocking {
        model.commit("pw", consent = false); settle()
        assertEquals(0, server.requestCount)
        assertTrue(model.message!!.contains("consent"))
        json("""{"reauthenticated":true}"""); json("""{"version":1,"sample_count":5}"""); json(enabledStatus)
        model.commit("pw", consent = true); settle()
        assertEquals("/hub/owner-recognition/reauth", server.takeRequest().path)
        val commit = server.takeRequest()
        assertEquals("/hub/voice-identity/enrollment/commit", commit.path)
        assertTrue(commit.body.readUtf8().contains("\"consent\":true"))
        assertEquals("Voice profile saved.", model.message)
    }

    @Test fun `a wrong password stops before anything is saved`() = runBlocking {
        json("""{"detail":"Invalid password"}""", 401)
        model.commit("nope", consent = true); settle()
        assertEquals(1, server.requestCount)
        assertEquals("That password is not right.", model.message)
    }

    @Test fun `cancelling and deleting a clip call the hub`() = runBlocking {
        json("""{"deleted":true}"""); json(enabledStatus)
        model.cancelEnrollment(); settle()
        val cancel = server.takeRequest(); assertEquals("DELETE", cancel.method); assertEquals("/hub/voice-identity/enrollment", cancel.path)
        server.takeRequest()
        json("""{"deleted":true}"""); json(enabledStatus)
        model.removeSample("abc"); settle()
        assertEquals("/hub/voice-identity/enrollment/samples/abc", server.takeRequest().path)
    }

    @Test fun `deleting the profile needs the password and clears the current result`() = runBlocking {
        json("""{"state":"unavailable","reasons":["not_calibrated"],"expires_in_seconds":10}"""); model.test(wav); settle()
        assertNotNull(model.testResult); assertNotNull(model.match())
        server.takeRequest()
        json("""{"reauthenticated":true}"""); json("""{"deleted":true}"""); json(enabledStatus)
        model.deleteProfile("pw"); settle()
        assertEquals("/hub/owner-recognition/reauth", server.takeRequest().path)
        val delete = server.takeRequest(); assertEquals("DELETE", delete.method); assertEquals("/hub/voice-identity/profile", delete.path)
        assertNull(model.testResult); assertNull(model.match())
    }

    @Test fun `a voice turn is one upload that asks the hub not to answer, and returns the transcript`() = runBlocking {
        json("""{"transcript":"what is on my calendar","message":null,"voice":{"state":"unavailable","utterance_id":"u","expires_in_seconds":10,"reasons":["not_calibrated"]}}""")
        assertEquals("what is on my calendar", model.transcribe(wav))
        val request = server.takeRequest()
        assertEquals("/hub/voice-identity/turn?converse=false", request.path); assertEquals("audio/wav", request.getHeader("Content-Type"))
        assertEquals(wav.toList(), request.body.readByteArray().toList())
        assertNotNull(request.getHeader("X-Reachy-Utterance-Id"))
        assertEquals("Owner match: unverified", model.match()!!.label)
        clock += 10_001
        assertNull(model.match())   // no lasting badge
    }

    @Test fun `a hub failure on a voice turn is an error for the caller and leaves the model usable`() = runBlocking {
        json("""{"detail":"Voice identity service unavailable"}""", 503)
        try { model.transcribe(wav); fail("expected an error") } catch (e: ApiException) { assertEquals(503, e.code) }
        json("""{"transcript":"hello","voice":{"state":"uncertain","expires_in_seconds":10,"reasons":["too_quiet"]}}""")
        assertEquals("hello", model.transcribe(wav))
        assertEquals("Owner match: inconclusive", model.match()!!.label)
    }

    @Test fun `a hub that is off says so rather than failing silently`() = runBlocking {
        json("""{"detail":"Voice identity is not enabled"}""", 404)
        model.test(wav); settle()
        assertEquals("Voice identity is not switched on at the hub.", model.message)
    }

    @Test fun `evaluation clips carry their label, recording needs the password, and deleting turns it off again`() = runBlocking {
        json("""{"reauthenticated":true}"""); json("""{"benchmark_enabled":true}"""); json("""{"benchmark_enabled":true,"voice_samples":[]}""")
        model.enableGv("pw"); settle()
        assertEquals("/hub/owner-recognition/reauth", server.takeRequest().path)
        val enable = server.takeRequest(); assertEquals("PUT", enable.method); assertTrue(enable.body.readUtf8().contains("true"))
        server.takeRequest()
        json("""{"sample_id":"c1","label":"role=trial;speaker=owner;condition=quiet"}"""); json("""{"benchmark_enabled":true,"voice_samples":[{"sample_id":"c1","label":"role=trial;speaker=owner;condition=quiet"}]}""")
        model.uploadGv(GV_PLAN.first { it.id == "quiet" }, wav, null); settle()
        val clip = server.takeRequest()
        assertEquals("/hub/owner-recognition/benchmark/voice/samples", clip.path); assertEquals("role=trial;speaker=owner;condition=quiet", clip.getHeader("X-Reachy-Benchmark-Label"))
        server.takeRequest()
        assertEquals(1, gvCounts(model.gv!!.voiceSamples)["quiet"])
        json("""{"reauthenticated":true}"""); json("""{"ok":true}"""); json("""{"benchmark_enabled":false}"""); json("""{"benchmark_enabled":false,"voice_samples":[]}""")
        model.deleteGvClips("pw"); settle()
        server.takeRequest()
        assertEquals("DELETE", server.takeRequest().method)
        assertTrue(server.takeRequest().body.readUtf8().contains("false"))
    }

    @Test fun `signing out forgets everything`() = runBlocking {
        json(enabledStatus); model.refresh(); until { model.status != null }
        model.clear()
        assertNull(model.status); assertNull(model.match()); assertFalse(model.hubCapture)
    }
}
