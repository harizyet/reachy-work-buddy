package app.reachy.companion

import app.reachy.companion.data.ClientIdentity
import app.reachy.companion.data.GV_PLAN
import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.ReachyApi
import app.reachy.companion.data.VoiceIdentityModel
import app.reachy.companion.data.Wav
import app.reachy.companion.data.gvCounts
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import kotlin.math.PI
import kotlin.math.sin

/**
 * The real Android client code (ReachyApi and VoiceIdentityModel) against a real in-process hub started from clients/android/e2e/android_voice_identity_hub_server.py.
 * Skipped unless REACHY_E2E_HUB is set, e.g. REACHY_E2E_HUB=http://127.0.0.1:18732 (and REACHY_E2E_CALIBRATED=true when the fixture was started `calibrated`).
 * A 220 Hz tone is the owner, 440 Hz is someone else. Fixture models stand in for ECAPA and Whisper; this checks the contract and the privacy/authority behaviour, not accuracy.
 */
class VoiceIdentityHubIntegrationTest {
    private val hub = System.getenv("REACHY_E2E_HUB")
    private val calibrated = System.getenv("REACHY_E2E_CALIBRATED") == "true"

    private fun tone(hz: Double, seconds: Double = 3.0, amp: Double = 0.4): ByteArray =
        Wav.encode(ShortArray((16000 * seconds).toInt()) { (amp * 32767 * sin(2 * PI * hz * it / 16000)).toInt().toShort() })

    private fun until(what: () -> Boolean) { val end = System.currentTimeMillis() + 10_000; while (!what() && System.currentTimeMillis() < end) Thread.sleep(10); assertTrue("timed out", what()) }

    @Test fun `enrol, check, chat unaffected, delete, and the evaluation clips, all against a real hub`() = runBlocking {
        assumeTrue(hub != null)
        var cookies: String? = null
        val api = ReachyApi(hub!!, PersistentCookieJar({ cookies }, { cookies = it }))
        api.login("owner", "correct-password")
        val model = VoiceIdentityModel(CoroutineScope(Dispatchers.Unconfined), { api }, { ClientIdentity("e2e-install", "JVM") }, { false })
        fun settle() { Thread.sleep(30); until { !model.busy } }

        model.refresh(); until { model.status != null }
        assertTrue(model.status!!.enabled && model.status!!.profile == null && model.hubCapture)
        assertEquals(calibrated, model.status!!.calibrated)

        // Enrolment: a silent clip is refused with a reason; five owner clips are enough; the silent one can be deleted first.
        model.addSample(Wav.encode(ShortArray(16000 * 3))); settle()
        assertTrue(model.message!!.startsWith("Clip not usable"))
        val bad = model.status!!.draft!!.samples.single()
        assertFalse(bad.qualityOk)
        model.removeSample(bad.sampleId); settle()
        for (hz in listOf(216.0, 220.0, 224.0, 218.0, 222.0)) { model.addSample(tone(hz)); settle() }
        assertEquals(5, model.status!!.draft!!.usableSamples)

        model.commit("wrong-password", consent = true); settle()
        assertEquals("That password is not right.", model.message); assertNull(model.status!!.profile)
        model.commit("correct-password", consent = true); settle()
        assertEquals("Voice profile saved.", model.message)
        assertEquals(5, model.status!!.profile!!.sampleCount); assertNull(model.status!!.draft)

        // Voice chat path: one upload gives the transcript and a result. The owner's voice and someone else's.
        assertEquals("hello from the phone", model.transcribe(tone(221.0)))
        val owner = model.match()!!
        assertEquals(if (calibrated) "Owner voice verified" else "Owner match: unverified", owner.label)
        assertEquals("hello from the phone", model.transcribe(tone(440.0)))
        assertEquals(if (calibrated) "Owner match: not verified" else "Owner match: unverified", model.match()!!.label)
        assertEquals("hello from the phone", model.transcribe(Wav.encode(ShortArray(16000 * 3))))   // a silent clip is inconclusive, never an error
        assertEquals("Owner match: inconclusive", model.match()!!.label)

        // A non-match never touches the session or what the owner can do: the same cookie still reaches every ordinary route.
        assertEquals("owner", api.me()); assertNotNull(api.userId())

        // Deleting the profile removes the basis for any result.
        model.deleteProfile("correct-password"); settle()
        assertNull(model.status!!.profile)
        model.transcribe(tone(220.0)); assertEquals("No voice profile", model.match()!!.label)

        // Evaluation clips: opt-in behind the password, labelled, counted, and removable.
        model.refreshGv(); until { model.gv != null }
        assertFalse(model.gv!!.benchmarkEnabled)
        model.enableGv("correct-password"); settle()
        assertTrue(model.gv!!.benchmarkEnabled)
        model.uploadGv(GV_PLAN.first { it.id == "replay" }, tone(220.0), null); settle()
        model.uploadGv(GV_PLAN.first { it.id == "other_person" }, tone(440.0), "Sam!"); settle()
        assertEquals(mapOf("replay" to 1, "other_person" to 1), gvCounts(model.gv!!.voiceSamples))
        assertTrue(model.gv!!.voiceSamples.mapNotNull { it.label }.contains("role=trial;speaker=Sam;condition=other_person"))
        model.deleteGvClips("correct-password"); settle()
        assertTrue(model.gv!!.voiceSamples.isEmpty()); assertFalse(model.gv!!.benchmarkEnabled)
    }
}
