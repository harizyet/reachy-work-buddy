package app.reachy.companion

import app.reachy.companion.data.Reminder
import app.reachy.companion.data.completedReminders
import app.reachy.companion.data.isOverdue
import app.reachy.companion.data.pendingReminders
import app.reachy.companion.data.reminderWhen
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.OffsetDateTime
import java.time.ZoneId
import java.util.Locale

class RemindersTest {
    private val utc = ZoneId.of("UTC")
    private val now = OffsetDateTime.parse("2026-10-07T15:00:00Z")
    private fun r(id: String, due: String, status: String = "pending") = Reminder(id, id, due, status)

    @Test fun `the due line reads Today, Tomorrow, Yesterday or a date with the time`() {
        assertEquals("Today, 4:00 PM", reminderWhen("2026-10-07T16:00:00Z", now, utc, Locale.US))
        assertEquals("Tomorrow, 9:00 AM", reminderWhen("2026-10-08T09:00:00Z", now, utc, Locale.US))
        assertEquals("Yesterday, 9:30 AM", reminderWhen("2026-10-06T09:30:00Z", now, utc, Locale.US))
        assertEquals("10/20/26, 6:00 PM", reminderWhen("2026-10-20T18:00:00Z", now, utc, Locale.US))
    }

    @Test fun `only an unfinished reminder that has passed is overdue`() {
        assertTrue(isOverdue(r("a", "2026-10-07T14:59:00Z"), now))
        assertFalse(isOverdue(r("b", "2026-10-07T15:01:00Z"), now))
        assertFalse(isOverdue(r("c", "2026-10-01T10:00:00Z", status = "done"), now))
    }

    @Test fun `pending reminders are soonest first and completed ones most recent first`() {
        val all = listOf(r("late", "2026-10-09T10:00:00Z"), r("soon", "2026-10-08T10:00:00Z"), r("old", "2026-10-01T10:00:00Z", "done"), r("newer", "2026-10-03T10:00:00Z", "done"))
        assertEquals(listOf("soon", "late"), pendingReminders(all).map { it.id })
        assertEquals(listOf("newer", "old"), completedReminders(all).map { it.id })
    }
}
