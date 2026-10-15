package app.reachy.companion

import app.reachy.companion.data.ApiException
import app.reachy.companion.data.CalendarItem
import app.reachy.companion.data.FeedBrief
import app.reachy.companion.data.MAX_SCHEDULED
import app.reachy.companion.data.MeetingReminder
import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.PreparedMeeting
import app.reachy.companion.data.ReachyApi
import app.reachy.companion.data.RecordingGate
import app.reachy.companion.data.RecordingPlan
import app.reachy.companion.data.ReminderIssue
import app.reachy.companion.data.ReminderSet
import app.reachy.companion.data.classLabel
import app.reachy.companion.data.decodePlan
import app.reachy.companion.data.encodePlan
import app.reachy.companion.data.firedKey
import app.reachy.companion.data.millis
import app.reachy.companion.data.onSchedule
import app.reachy.companion.data.planReminders
import app.reachy.companion.data.preparedFrom
import app.reachy.companion.data.pruneFired
import app.reachy.companion.data.reconcile
import app.reachy.companion.data.recordingGate
import app.reachy.companion.data.recordingTitle
import app.reachy.companion.data.reminderIssues
import app.reachy.companion.data.reminderNote
import app.reachy.companion.data.reminderText
import app.reachy.companion.data.reminderTitle
import app.reachy.companion.data.scheduleTitle
import app.reachy.companion.data.scheduleWhen
import app.reachy.companion.data.scheduledText
import app.reachy.companion.data.staleNotifications
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.ZoneId

/** Meeting reminders (ADR 0035): what to schedule, cancel and re-arm, what a notification says, when a recording may start, and what the hub's real payload looks like. */
class MeetingRemindersTest {
    private val zone = ZoneId.of("Asia/Singapore")
    private val now = millis("2026-10-12T09:00:00+08:00")

    private fun reminder(key: String, start: String, notify: String = start, title: String? = "Design review", classification: String = "meeting") =
        MeetingReminder(eventKey = key, title = title, start = start, end = start, notifyAt = notify, classification = classification)

    private fun set(vararg reminders: MeetingReminder, feed: FeedBrief = FeedBrief(configured = true, freshness = "fresh")) =
        ReminderSet(generatedAt = "2026-10-12T09:00:00+08:00", reminders = reminders.toList(), feed = feed)

    private val review = reminder("ics:a:0", "2026-10-13T14:00:00+08:00", "2026-10-13T13:55:00+08:00")

    // --- planning ---------------------------------------------------------------------------------------------------------------------------------------------

    @Test fun `a future meeting is scheduled at its notify time`() {
        val planned = planReminders(set(review), now, emptySet()).single()
        assertEquals(millis("2026-10-13T13:55:00+08:00"), planned.fireAtMs)
        assertEquals(millis("2026-10-13T14:00:00+08:00"), planned.startMs)
        assertFalse(planned.late)
    }

    @Test fun `a meeting that has started is not scheduled`() {
        assertTrue(planReminders(set(reminder("ics:a:0", "2026-10-12T08:59:00+08:00", "2026-10-12T08:54:00+08:00")), now, emptySet()).isEmpty())
    }

    @Test fun `a reminder whose time passed but whose meeting has not started fires once at once`() {
        val late = reminder("ics:a:0", "2026-10-12T09:03:00+08:00", "2026-10-12T08:58:00+08:00")
        val planned = planReminders(set(late), now, emptySet()).single()
        assertTrue(planned.late)
        assertEquals(now + 1_000, planned.fireAtMs)
        assertTrue(planReminders(set(late), now, setOf(planned.firedKey)).isEmpty())  // shown or dismissed: not again after the next refresh, restart or revision
    }

    @Test fun `the same meeting seen again after it was shown is not shown again but a moved one is`() {
        val shown = setOf(firedKey("ics:a:0", millis("2026-10-13T14:00:00+08:00")))
        assertTrue(planReminders(set(review), now, shown).isEmpty())
        val moved = review.copy(start = "2026-10-13T16:00:00+08:00", notifyAt = "2026-10-13T15:55:00+08:00")
        assertEquals(1, planReminders(set(moved), now, shown).size)  // a new start time is a new reminder
    }

    @Test fun `only meetings, once per key, bad times skipped, earliest first and bounded`() {
        val other = reminder("ics:b:0", "2026-10-13T10:00:00+08:00", classification = "personal_appointment")
        val repeated = review.copy(title = "Same key again")
        val broken = reminder("ics:c:0", "not a time")
        val soon = reminder("ics:d:0", "2026-10-12T10:00:00+08:00", "2026-10-12T09:55:00+08:00")
        val planned = planReminders(set(review, other, repeated, broken, soon), now, emptySet())
        assertEquals(listOf("ics:d:0", "ics:a:0"), planned.map { it.key })
        assertEquals("Design review", planned.last().reminder.title)
        val many = (1..100).map { reminder("ics:k$it:0", "2026-10-13T${"%02d".format(it % 10 + 8)}:00:00+08:00") }
        assertEquals(MAX_SCHEDULED, planReminders(set(*many.toTypedArray()), now, emptySet()).size)
    }

    // --- reconcile: refresh, change, cancel, restart --------------------------------------------------------------------------------------------------------

    @Test fun `new reminders are scheduled and unchanged ones are left alone`() {
        val planned = planReminders(set(review), now, emptySet())
        val first = reconcile(emptyMap(), planned)
        assertEquals(planned, first.schedule); assertTrue(first.cancel.isEmpty())
        val again = reconcile(mapOf(planned.single().key to planned.single().fireAtMs), planned)
        assertTrue(again.schedule.isEmpty() && again.cancel.isEmpty())
    }

    @Test fun `a moved meeting is rescheduled and a cancelled or removed one is cancelled`() {
        val armed = mapOf("ics:a:0" to millis("2026-10-13T13:55:00+08:00"), "ics:gone:0" to millis("2026-10-13T09:00:00+08:00"))
        val moved = review.copy(start = "2026-10-13T16:00:00+08:00", notifyAt = "2026-10-13T15:55:00+08:00")
        val change = reconcile(armed, planReminders(set(moved), now, emptySet()))
        assertEquals(setOf("ics:gone:0"), change.cancel)
        assertEquals(listOf("ics:a:0"), change.schedule.map { it.key })
        assertEquals(millis("2026-10-13T15:55:00+08:00"), change.schedule.single().fireAtMs)
    }

    @Test fun `a restart re-arms everything that is still wanted`() {
        val planned = planReminders(set(review), now, emptySet())
        val armed = mapOf(planned.single().key to planned.single().fireAtMs)
        assertTrue(reconcile(armed, planned).schedule.isEmpty())
        assertEquals(1, reconcile(armed, planned, rearmAll = true).schedule.size)
    }

    @Test fun `an old record of shown reminders is forgotten`() {
        val old = firedKey("ics:a:0", now - 2 * 24 * 3_600_000L); val recent = firedKey("ics:b:0", now - 3_600_000L)
        assertEquals(setOf(recent), pruneFired(setOf(old, recent, "garbage"), now))
    }

    // --- what the notification says --------------------------------------------------------------------------------------------------------------------------

    @Test fun `a missing title is a generic one, never invented`() {
        assertEquals("Meeting", reminderTitle(null)); assertEquals("Meeting", reminderTitle("   "))
        assertEquals("Design review", reminderTitle(" Design review "))
    }

    @Test fun `the text counts down to the start`() {
        val start = millis("2026-10-12T14:00:00+08:00")
        assertEquals("Starts in 5 minutes · 14:00", reminderText(start, start - 300_000, zone))
        assertEquals("Starts in 5 minutes · 14:00", reminderText(start, start - 241_000, zone))
        assertEquals("Starts in 1 minute · 14:00", reminderText(start, start - 30_000, zone))
        assertEquals("Starting now · 14:00", reminderText(start, start, zone))
        assertEquals("Starting now · 14:00", reminderText(start, start + 5_000, zone))
    }

    // --- the notification action ------------------------------------------------------------------------------------------------------------------------------

    @Test fun `an intent is accepted only with a feed key, a sane time and a bounded title`() {
        assertEquals(PreparedMeeting("ics:a:0", "Design review", now + 1000), preparedFrom("ics:a:0", " Design review ", now + 1000, now))
        assertNull(preparedFrom(null, "x", now, now)); assertNull(preparedFrom("google:abc", "x", now, now)); assertNull(preparedFrom("ics:" + "x".repeat(200), "x", now, now))
        assertNull(preparedFrom("ics:a:0", "x", 0L, now)); assertNull(preparedFrom("ics:a:0", "x", now + 90L * 24 * 3_600_000L, now))
        assertEquals(200, preparedFrom("ics:a:0", "t".repeat(500), now, now)!!.title!!.length)
        assertNull(preparedFrom("ics:a:0", "   ", now, now)!!.title)
    }

    @Test fun `the recording is titled from the calendar or, with no title, the usual dated default`() {
        assertEquals("Design review", recordingTitle(PreparedMeeting("ics:a:0", "Design review", now), zone))
        assertEquals("Meeting 12 Oct 09:00", recordingTitle(PreparedMeeting("ics:a:0", null, now), zone))
        assertEquals("Scheduled Mon 12 Oct, 09:00", scheduledText(now, zone))
    }

    @Test fun `starting twice never makes two recordings`() {
        val p = PreparedMeeting("ics:a:0", "Design review", now)
        assertEquals(RecordingGate.Ready, recordingGate(p, emptyMap(), emptySet(), false, null))
        assertEquals(RecordingGate.RecordingThis, recordingGate(p, emptyMap(), emptySet(), true, "ics:a:0"))
        assertEquals(RecordingGate.RecordingSomethingElse, recordingGate(p, emptyMap(), emptySet(), true, "ics:other:0"))
        assertEquals(RecordingGate.RecordingSomethingElse, recordingGate(p, emptyMap(), emptySet(), true, null))
        assertEquals(RecordingGate.WaitingToUpload, recordingGate(p, emptyMap(), setOf("ics:a:0"), false, null))
        assertEquals(RecordingGate.AlreadyRecorded("m1"), recordingGate(p, mapOf("ics:a:0" to "m1"), emptySet(), false, null))
        // the next week's occurrence of a recurring meeting has its own key, so it can be recorded
        assertEquals(RecordingGate.Ready, recordingGate(p.copy(key = "ics:a:20261019T013000Z"), mapOf("ics:a:0" to "m1"), emptySet(), false, null))
    }

    @Test fun `the note beside a clip survives a round trip and garbage is ignored`() {
        val plan = RecordingPlan("ics:a:0", "Design review", now)
        assertEquals(plan, decodePlan(encodePlan(plan)))
        assertNull(decodePlan("not json")); assertNull(decodePlan(""))
        assertEquals(RecordingPlan("ics:a:0", null, 5L), decodePlan("""{"key":"ics:a:0","startMs":5,"extra":1}"""))
    }

    // --- can the phone deliver them ---------------------------------------------------------------------------------------------------------------------------

    private fun issues(enabled: Boolean = true, notifications: Boolean = true, channel: Boolean = true, exact: Boolean = true, set: ReminderSet? = set(review), failed: Boolean = false) =
        reminderIssues(enabled, notifications, channel, exact, set, failed)

    @Test fun `a healthy phone has no issues`() = assertTrue(issues().isEmpty())

    @Test fun `each failure is named, worst first`() {
        assertEquals(listOf(ReminderIssue.Off), issues(enabled = false, notifications = false))
        assertEquals(ReminderIssue.NotificationsBlocked, issues(notifications = false).first())
        assertEquals(listOf(ReminderIssue.ChannelBlocked), issues(channel = false))
        assertEquals(listOf(ReminderIssue.NeverSynced), issues(set = null))
        assertEquals(listOf(ReminderIssue.HubUnreachable), issues(failed = true))  // offline: what was loaded still works, and the line says so
        assertEquals(listOf(ReminderIssue.ApproximateTimes), issues(exact = false))
        assertEquals(listOf(ReminderIssue.FeedNotSet), issues(set = set(feed = FeedBrief(configured = false))))
        assertEquals(listOf(ReminderIssue.FeedStale), issues(set = set(feed = FeedBrief(configured = true, freshness = "stale"))))
        assertEquals(listOf(ReminderIssue.FeedError), issues(set = set(feed = FeedBrief(configured = true, freshness = "stale", error = "http_503"))))
    }

    // --- the hub's real payload -------------------------------------------------------------------------------------------------------------------------------

    private lateinit var server: MockWebServer
    private var stored: String? = null
    private lateinit var api: ReachyApi
    private fun resource(name: String) = checkNotNull(javaClass.getResource("/$name")).readText()

    @Before fun setUp() {
        server = MockWebServer().apply { start() }
        api = ReachyApi(server.url("/hub").toString(), PersistentCookieJar({ stored }, { stored = it }))
    }

    @After fun tearDown() = server.shutdown()

    @Test fun `the phone reads the reminders the core really produces`() = runBlocking {
        server.enqueue(MockResponse().setBody(resource("calendar-reminders.json")).setHeader("Content-Type", "application/json"))
        val reminders = api.meetingReminders()
        val request = server.takeRequest()
        assertEquals("/hub/calendar-feed/reminders", request.path); assertEquals("1", request.getHeader("X-Reachy-CSRF"))
        assertEquals(4, reminders.reminders.size)
        assertEquals(5, reminders.leadMinutes); assertTrue(reminders.feed.configured); assertEquals("fresh", reminders.feed.freshness)
        assertTrue(reminders.reminders.all { it.classification == "meeting" && it.eventKey.startsWith("ics:") })
        assertEquals(1, reminders.reminders.count { it.title == null })  // the untitled meeting stays untitled
        val review = reminders.reminders.single { it.title == "Design review" }
        assertEquals(millis(review.start) - 300_000, millis(review.notifyAt))
        // and it plans: four reminders from a phone that last synced at the generation time, the first being the 09:30 sync
        val planned = planReminders(reminders, millis(reminders.generatedAt), emptySet())
        assertEquals(4, planned.size); assertEquals("Weekly sync", planned.first().reminder.title)
    }

    @Test fun `the phone reads the events and their classification as the web does`() = runBlocking {
        server.enqueue(MockResponse().setBody(resource("calendar-events.json")).setHeader("Content-Type", "application/json"))
        val events = api.calendarEvents("2026-10-12T00:00:00+08:00", "2026-10-22T00:00:00+08:00")
        val request = server.takeRequest()
        assertTrue(request.path!!.startsWith("/hub/calendar-feed/events?start=")); assertTrue(request.path!!.contains("end="))
        val byTitle = events.associateBy { it.title }
        assertEquals("Meeting", classLabel(byTitle.getValue("Design review")))
        assertEquals("Appointment", classLabel(byTitle.getValue("Dentist appointment")))
        assertEquals("Leave", classLabel(byTitle.getValue("Annual leave")))
        assertEquals("Busy", classLabel(byTitle.getValue("Busy"))); assertTrue(byTitle.getValue("Busy").redacted)
        assertEquals("Timed event", classLabel(byTitle.getValue("Quiet time")))
        assertEquals("Untitled event", scheduleTitle(events.single { it.titleMissing }))
        assertTrue(events.none { it.title.contains("Secret") })
        assertFalse(onSchedule(events.single { it.title == "Budget review" }))  // declined
        assertEquals("Mon 19 Oct to Wed 21 Oct", scheduleWhen(byTitle.getValue("Annual leave"), zone))  // the exclusive end is not a leave day
        assertEquals("Reminder on", reminderNote(byTitle.getValue("Design review")))
        assertNull(reminderNote(byTitle.getValue("Dentist appointment")))
    }

    @Test fun `a hub error is an ApiException and nothing is stored`() = runBlocking<Unit> {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Login required"}"""))
        try { api.meetingReminders(); throw AssertionError("expected 401") } catch (e: ApiException) { assertTrue(e.unauthorized) }
    }

    @Test fun `schedule lines for timed, single and multi day events`() {
        fun item(start: String, end: String, allDay: Boolean) = CalendarItem(title = "x", start = start, end = end, allDay = allDay)
        assertEquals("Tue 13 Oct, 14:00–15:00", scheduleWhen(item("2026-10-13T14:00:00+08:00", "2026-10-13T15:00:00+08:00", false), zone))
        assertEquals("Fri 30 Oct", scheduleWhen(item("2026-10-30T00:00:00+08:00", "2026-10-31T00:00:00+08:00", true), zone))
        assertEquals("Tue 27 Oct to Wed 28 Oct", scheduleWhen(item("2026-10-27T00:00:00+08:00", "2026-10-29T00:00:00+08:00", true), zone))
        assertNotNull(Json.parseToJsonElement("{}"))
    }

    // --- a notification that is showing must not outlive its meeting ---------------------------------------------------------------------------------------

    @Test fun `a showing notification is taken down when its meeting was moved, cancelled or removed, and left alone when nothing changed`() {
        val start = millis(review.start)
        val shown = mapOf("ics:a:0" to start, "ics:b:0" to start, "ics:c:0" to start, "ics:d:0" to start)
        val moved = reminder("ics:b:0", "2026-10-13T16:00:00+08:00")  // a new start
        val personal = reminder("ics:c:0", review.start, classification = "unknown_timed")  // reclassified: no longer a meeting
        // ics:d:0 is absent from the set: cancelled, declined, removed or already started
        val stale = staleNotifications(shown, set(review, moved, personal))
        assertEquals(setOf("ics:b:0", "ics:c:0", "ics:d:0"), stale)
        assertTrue(staleNotifications(mapOf("ics:a:0" to start), set(review)).isEmpty())  // unchanged: the notification stays
        assertTrue(staleNotifications(emptyMap(), set(review)).isEmpty())
        assertEquals(setOf("ics:a:0"), staleNotifications(mapOf("ics:a:0" to start), set()))  // an empty calendar clears every notification
    }
}
