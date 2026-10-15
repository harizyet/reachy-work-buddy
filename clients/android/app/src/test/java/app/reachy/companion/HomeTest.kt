package app.reachy.companion

import app.reachy.companion.data.HomeEvent
import app.reachy.companion.data.HomeRef
import app.reachy.companion.data.Section
import app.reachy.companion.data.briefHeadline
import app.reachy.companion.data.eventTime
import app.reachy.companion.data.mergeSection
import app.reachy.companion.data.parseBrief
import app.reachy.companion.data.parseHome
import app.reachy.companion.data.savedCopyLine
import app.reachy.companion.data.sectionFor
import app.reachy.companion.data.stateLine
import app.reachy.companion.data.weatherLines
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

/** The Home dashboard's pure logic: parsing the hub's snapshot, merging one refreshed section, where a tap goes, and what each state says. */
class HomeTest {
    private val utc = ZoneId.of("UTC")

    private val full = """
    {"generated_at":"2030-01-02T08:00:00+00:00","date":"2030-01-02","timezone":"UTC","partial":false,"restricted":false,
     "sources":{"schedule":"ok","tasks":"ok","reminders":"ok","reviews":"ok","weather":"ok"},
     "quick_actions":[{"id":"add_task","label":"Add a task","ref":{"screen":"tasks"}}],
     "unknown_future_field":{"a":1},
     "schedule":{"status":"ok","generation":7,"feed_configured":true,"feed":{"configured":true,"freshness":"fresh","age_seconds":30,"error":null},"on_leave":true,
       "all_day":[{"id":"l","title":"Annual leave","start":"2030-01-02T00:00:00+00:00","end":"2030-01-02T23:59:00+00:00","all_day":true,"classification":"leave_or_ooo","location":null,"ref":{"screen":"calendar","id":"l"}}],
       "events":[{"id":"b","title":"Busy","start":"2030-01-02T11:00:00+00:00","end":"2030-01-02T12:00:00+00:00","all_day":false,"classification":"busy_private","location":null,"redacted":true,"ref":{"screen":"calendar","id":"b"}}],
       "next_event":null},
     "tasks":{"status":"ok","total":3,"shown":1,"from_meetings":1,"items":[{"id":"t1","text":"Contact the vendor","origin":{"kind":"meeting","meeting_title":"Cluster migration"},"ref":{"screen":"tasks","id":"t1"}}]},
     "reminders":{"status":"ok","upcoming_days":7,"overdue":[{"id":"r1","text":"Pay rent","due_at":"2030-01-02T08:00:00+00:00","ref":{"screen":"reminders","id":"r1"}}],"today":[],"upcoming":[]},
     "reviews":{"status":"ok","total":2,"note_proposals":{"status":"ok","count":1,"items":[{"id":"p1","text":"Renew the certificate","note_title":"Weekly","ref":{"screen":"notes","id":"n1"}}]},
                "meeting_actions":{"status":"ok","count":1,"items":[{"id":"i1","text":"Update the schedule","assignee":"Hariz","meeting_title":"Cluster migration","ref":{"screen":"meetings","id":"m1"}}]}},
     "weather":{"status":"ok","location":"Singapore","observed_at":"2030-01-02T14:00:00+08:00","age_seconds":0,"attribution":{"name":"Open-Meteo.com","url":"https://open-meteo.com/","license":"CC BY 4.0"},
       "units":{"temperature":"°C","precipitation":"mm","probability":"%"},"current":{"temperature":30.4,"feels_like":36.0,"summary":"Light rain"},
       "today":{"high":32.1,"low":26.0,"precipitation_total":7.5,"precipitation_probability":85.0,"summary":"Rain showers"}}}
    """.trimIndent()

    @Test fun `the snapshot parses, ignores fields it does not know and keeps sections separate`() {
        val home = parseHome(full)
        assertEquals("2030-01-02", home.date); assertEquals(5, home.sources.size)
        assertTrue(home.schedule!!.onLeave); assertEquals("leave_or_ooo", home.schedule!!.allDay.single().classification)
        assertEquals(3, home.tasks!!.total); assertEquals("Cluster migration", home.tasks!!.items.single().origin!!.meetingTitle)
        assertEquals(1, home.reviews!!.noteProposals!!.count); assertEquals("Hariz", home.reviews!!.meetingActions!!.items.single().assignee)
        assertEquals("Open-Meteo.com", home.weather!!.attribution!!.name)
        assertEquals("add_task", home.quickActions.single().id)
    }

    @Test fun `a busy only event keeps its placeholder and no detail`() {
        val e = parseHome(full).schedule!!.events.single()
        assertEquals("Busy", e.title); assertNull(e.location); assertTrue(e.redacted)
        assertTrue(eventTime(e, utc).matches(Regex("11.*–12.*")))  // the range, in the phone's own 12 or 24 hour style
    }

    @Test fun `an all day banner shows its class not a time range`() {
        val leave = parseHome(full).schedule!!.allDay.single()
        assertEquals("Leave", eventTime(leave, utc))
        assertEquals("All day", eventTime(HomeEvent(allDay = true, classification = null), utc))
    }

    @Test fun `a restricted or sparse snapshot parses with nothing invented`() {
        val locked = parseHome("""{"generated_at":"x","restricted":true,"sources":{"tasks":"restricted"},"tasks":{"status":"restricted"},"quick_actions":[]}""")
        assertTrue(locked.restricted); assertEquals(0, locked.tasks!!.total); assertTrue(locked.tasks!!.items.isEmpty())
        assertNull(locked.schedule); assertNull(locked.reviews)
        val empty = parseHome("""{"generated_at":"x","sources":{},"schedule":{"status":"empty","events":[],"all_day":[],"next_event":null,"feed_configured":false}}""")
        assertEquals(false, empty.schedule!!.feedConfigured); assertEquals("empty", empty.schedule!!.status)
    }

    @Test fun `one refreshed section replaces only itself and partial follows the sources`() {
        val old = parseHome(full).let { it.copy(partial = true, sources = it.sources + ("weather" to "unavailable"), weather = it.weather!!.copy(status = "unavailable")) }
        val fresh = parseHome("""{"generated_at":"later","sources":{"weather":"ok"},"weather":{"status":"ok","location":"Singapore"}}""")
        val merged = mergeSection(old, fresh, "weather")
        assertEquals("ok", merged.weather!!.status); assertFalse(merged.partial); assertEquals("later", merged.generatedAt)
        assertEquals(old.tasks, merged.tasks); assertEquals(old.schedule, merged.schedule); assertEquals(old.reviews, merged.reviews)
        val broken = mergeSection(merged, parseHome("""{"generated_at":"x","sources":{"tasks":"unavailable"},"tasks":{"status":"unavailable"}}"""), "tasks")
        assertTrue(broken.partial); assertEquals("unavailable", broken.tasks!!.status); assertEquals(merged.reminders, broken.reminders)
    }

    @Test fun `every reference opens an existing screen and tasks open the screen that lists them`() {
        assertEquals(Section.Calendar, sectionFor(HomeRef("calendar", "x")))
        assertEquals(Section.Reminders, sectionFor(HomeRef("reminders"))); assertEquals(Section.Reminders, sectionFor(HomeRef("tasks")))
        assertEquals(Section.Notes, sectionFor(HomeRef("notes"))); assertEquals(Section.Meetings, sectionFor(HomeRef("meetings", "m1")))
        assertEquals(Section.Talk, sectionFor(HomeRef("talk")))
        assertNull(sectionFor(HomeRef("something-new"))); assertNull(sectionFor(null))
    }

    @Test fun `every state a source can be in has its own wording and content shows no state line`() {
        assertEquals("Not shown in this context.", stateLine("restricted"))
        assertTrue(stateLine("unavailable")!!.contains("could not be read"))
        assertEquals("Weather is turned off.", stateLine("off", "Weather is turned off."))
        assertEquals("Not loaded yet.", stateLine(null))
        for (content in listOf("ok", "empty", "stale", "partial", "not_configured")) assertNull(content, stateLine(content))
    }

    @Test fun `weather is only what the provider sent, with units and an honest missing value`() {
        val w = parseHome(full).weather!!
        assertEquals(listOf("Light rain · 30°C (feels like 36°C)", "Today 26°C to 32°C · Rain showers", "Rain today: 7.5 mm · up to 85% chance"), weatherLines(w))
        assertEquals(emptyList<String>(), weatherLines(parseHome("""{"generated_at":"x","weather":{"status":"unavailable"}}""").weather!!))
        val partial = w.copy(current = w.current!!.copy(temperature = null, feelsLike = null))
        assertEquals("Light rain · —", weatherLines(partial).first())
    }

    @Test fun `the offline line says how old the saved copy is`() {
        val checked = java.time.Instant.parse("2030-01-02T08:00:00Z").toEpochMilli()
        assertEquals("Showing the copy saved on this phone from 08:00 (just now).", savedCopyLine(checked, checked + 10_000, utc))
        assertEquals("Showing the copy saved on this phone from 08:00 (45 min ago).", savedCopyLine(checked, checked + 45 * 60_000, utc))
        assertEquals("Showing the copy saved on this phone from 08:00 (3 h ago).", savedCopyLine(checked, checked + 3 * 3_600_000, utc))
        assertTrue(savedCopyLine(checked, checked + 2 * 86_400_000L, utc).endsWith("(2 d ago)."))
    }

    @Test fun `the briefing says whether it is the model's wording or the plain lines and marks suggestions`() {
        val generated = parseBrief("""{"mode":"generated","text":"-","narrative":"You have Standup.","model":"qwen","lines":[{"category":"calendar","status":"confirmed","text":"Standup","ref":{"screen":"calendar"}},{"category":"suggestion","status":"pending_review","text":"1 note suggestion","ref":null}]}""")
        assertTrue(briefHeadline(generated).contains("Reworded by the local model (qwen)")); assertTrue(briefHeadline(generated).contains("which are the record"))
        assertEquals("pending_review", generated.lines[1].status); assertNull(generated.lines[1].ref)
        val fallback = parseBrief("""{"mode":"deterministic","text":"-","fallback":"unverified_wording","lines":[]}""")
        assertEquals("A written summary was not available, so this is the plain briefing.", briefHeadline(fallback))
        assertEquals("Plain briefing.", briefHeadline(parseBrief("""{"mode":"deterministic","text":"-","fallback":null,"lines":[]}""")))
    }
}
