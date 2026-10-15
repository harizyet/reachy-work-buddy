package app.reachy.companion

import app.reachy.companion.data.Alarm
import app.reachy.companion.data.Verdict
import app.reachy.companion.data.phoneVerdict
import app.reachy.companion.data.reachyCouldNotPlay
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.OffsetDateTime

class AlarmFallbackTest {
    private val due = OffsetDateTime.parse("2026-10-08T07:00:00Z").toInstant().toEpochMilli()
    private fun alarm(
        delivery: String? = null, firedAt: String? = "2026-10-08T07:00:01Z", enabled: Boolean = true, status: String = "fired", dueAt: String = "2026-10-08T07:00:00Z",
    ) = Alarm(id = "a", label = "wake", dueAt = dueAt, status = status, enabled = enabled, delivery = delivery, firedAt = firedAt)

    @Test fun `the phone rings when Reachy was offline, found nobody, or could not play it`() {
        assertEquals(Verdict.Ring("Reachy is offline"), phoneVerdict(alarm("telegram: robot unavailable"), due))
        assertEquals(Verdict.Ring("Reachy did not find anyone in the room"), phoneVerdict(alarm("telegram: not played, nobody detected"), due))
        assertEquals(Verdict.Ring("Reachy is offline"), phoneVerdict(alarm("telegram: robot unavailable (telegram send failed)"), due))
        assertTrue(phoneVerdict(alarm("failed: playback error"), due) is Verdict.Ring)
    }

    @Test fun `the phone stays quiet when Reachy played it or when silence was chosen`() {
        assertEquals(Verdict.Done, phoneVerdict(alarm("played"), due))
        assertEquals(Verdict.Done, phoneVerdict(alarm("stopped by owner"), due))
        assertEquals(Verdict.Done, phoneVerdict(alarm("telegram: privacy mode"), due))
        assertEquals(Verdict.Done, phoneVerdict(alarm("telegram: do not disturb or meeting"), due))
        assertNull(reachyCouldNotPlay("played"))
    }

    @Test fun `it waits until the hub has recorded what happened to this ring`() {
        assertEquals(Verdict.Wait, phoneVerdict(alarm(delivery = null), due))                                   // picked up, no outcome yet
        assertEquals(Verdict.Wait, phoneVerdict(alarm(firedAt = null, status = "scheduled"), due))              // not picked up yet
        // the delivery of an earlier ring of a repeating alarm is not this ring's
        assertEquals(Verdict.Wait, phoneVerdict(alarm("played", firedAt = "2026-10-07T07:00:01Z", status = "scheduled"), due))
    }

    @Test fun `a phone copy that was switched off, moved or deleted elsewhere is dropped`() {
        assertEquals(Verdict.Done, phoneVerdict(alarm(firedAt = null, status = "scheduled", enabled = false), due))
        assertEquals(Verdict.Done, phoneVerdict(alarm(firedAt = null, status = "scheduled", dueAt = "2026-10-08T08:30:00Z"), due))
        assertEquals(Verdict.Done, phoneVerdict(alarm(status = "cancelled"), due))
        assertEquals(Verdict.Done, phoneVerdict(null, due))
    }
}
