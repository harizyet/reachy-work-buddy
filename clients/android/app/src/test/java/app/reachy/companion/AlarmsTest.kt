package app.reachy.companion

import app.reachy.companion.data.Alarm
import app.reachy.companion.data.clockOf
import app.reachy.companion.data.isOn
import app.reachy.companion.data.listedAlarms
import app.reachy.companion.data.repeatText
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

class AlarmsTest {
    private val utc = ZoneId.of("UTC")
    private fun alarm(id: String, due: String, status: String = "scheduled", enabled: Boolean = true, repeat: List<Int> = emptyList()) =
        Alarm(id = id, label = id, dueAt = due, status = status, enabled = enabled, repeat = repeat)

    @Test fun `repeat days read like the Clock app`() {
        assertEquals("", repeatText(emptyList()))
        assertEquals("Weekdays", repeatText(listOf(4, 3, 2, 1, 0)))
        assertEquals("Weekends", repeatText(listOf(6, 5)))
        assertEquals("Every day", repeatText((0..6).toList()))
        assertEquals("Mon, Wed", repeatText(listOf(2, 0)))
    }

    @Test fun `twelve hour clock and the wire format`() {
        assertEquals("12:05 AM", clockOf(0, 5).let { "${it.text} ${it.suffix}" })
        assertEquals("12:00 PM", clockOf(12, 0).let { "${it.text} ${it.suffix}" })
        assertEquals("5:30 PM", clockOf(17, 30).let { "${it.text} ${it.suffix}" })
        assertEquals("17:30", clockOf(17, 30).wire)
        assertEquals("00:05", clockOf(0, 5).wire)
        assertEquals("12:00", clockOf(12, 0).wire)
        assertEquals("6:15 AM", clockOf(alarm("a", "2030-01-02T06:15:00Z"), utc).let { "${it.text} ${it.suffix}" })
    }

    @Test fun `the switch is on only for an enabled alarm that has not rung`() {
        assertTrue(isOn(alarm("a", "2030-01-02T06:15:00Z")))
        assertFalse(isOn(alarm("b", "2030-01-02T06:15:00Z", enabled = false)))
        assertFalse(isOn(alarm("c", "2030-01-02T06:15:00Z", status = "fired")))
    }

    @Test fun `the list is ordered by time of day and hides deleted alarms`() {
        val listed = listedAlarms(listOf(
            alarm("late", "2030-01-02T17:30:00Z"), alarm("gone", "2030-01-02T01:00:00Z", status = "cancelled"), alarm("early", "2030-01-09T06:15:00Z"),
        ), utc)
        assertEquals(listOf("early", "late"), listed.map { it.id })
    }
}
