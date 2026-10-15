package app.reachy.companion

import app.reachy.companion.data.MEETING_DEEP_LINK
import app.reachy.companion.data.NavState
import app.reachy.companion.data.Primary
import app.reachy.companion.data.Section
import app.reachy.companion.data.decodeNav
import app.reachy.companion.data.encode
import app.reachy.companion.data.hasSecondary
import app.reachy.companion.data.sectionsOf
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The navigation hierarchy: five primary destinations (Home first and the default), every screen reachable exactly once, where a deep link lands and what a group restores. */
class NavigationTest {
    @Test fun `five primary destinations hold the eight screens and Home is first`() {
        assertEquals(listOf("Home", "Talk", "Planner", "Meetings", "Library"), Primary.entries.map { it.title })
        assertEquals(listOf(Section.Home), sectionsOf(Primary.Home))
        assertEquals(listOf(Section.Calendar, Section.Reminders, Section.Alarms), sectionsOf(Primary.Planner))
        assertEquals(listOf(Section.Notes, Section.Documents), sectionsOf(Primary.Library))
        assertEquals(listOf(Section.Talk), sectionsOf(Primary.Talk)); assertEquals(listOf(Section.Meetings), sectionsOf(Primary.Meetings))
        assertEquals(Section.entries.toSet(), Primary.entries.flatMap { sectionsOf(it) }.toSet())  // nothing is unreachable
        assertEquals(Section.entries.size, Primary.entries.sumOf { sectionsOf(it).size })  // and nothing is in two places
    }

    @Test fun `only the groups have secondary navigation`() {
        assertTrue(hasSecondary(Primary.Planner) && hasSecondary(Primary.Library))
        assertFalse(hasSecondary(Primary.Home) || hasSecondary(Primary.Talk) || hasSecondary(Primary.Meetings))
    }

    @Test fun `a group comes back on the screen that was open`() {
        var nav = NavState()
        assertEquals(Primary.Home, nav.primary); assertEquals(Section.Home, nav.current)  // signing in lands on Home
        nav = nav.selectPrimary(Primary.Talk); assertEquals(Section.Talk, nav.current)
        nav = nav.selectPrimary(Primary.Planner); assertEquals(Section.Calendar, nav.current)
        nav = nav.open(Section.Alarms); assertEquals(Section.Alarms, nav.current)
        nav = nav.selectPrimary(Primary.Meetings); assertEquals(Section.Meetings, nav.current)
        nav = nav.selectPrimary(Primary.Library); nav = nav.open(Section.Documents)
        nav = nav.selectPrimary(Primary.Planner); assertEquals(Section.Alarms, nav.current)  // not the first screen of the group
        nav = nav.selectPrimary(Primary.Library); assertEquals(Section.Documents, nav.current)
    }

    @Test fun `a deep link from a meeting reminder lands on Meetings from anywhere without losing the groups' positions`() {
        assertEquals(Section.Meetings, MEETING_DEEP_LINK)
        val before = NavState(Primary.Planner, Section.Reminders, Section.Documents)
        val after = before.open(MEETING_DEEP_LINK)
        assertEquals(Primary.Meetings, after.primary); assertEquals(Section.Meetings, after.current)
        assertEquals(Section.Reminders, after.planner); assertEquals(Section.Documents, after.library)
        assertEquals(Section.Talk, after.open(Section.Talk).current)  // "use as context" returns to Talk
        assertEquals(Section.Meetings, NavState().open(MEETING_DEEP_LINK).current)  // from the new default too: a notification never lands on Home
        assertEquals(Section.Home, NavState(Primary.Library, Section.Alarms, Section.Documents).selectPrimary(Primary.Home).current)
    }

    @Test fun `the position survives a save and restore, and a corrupt one falls back to Home`() {
        val nav = NavState(Primary.Library, Section.Alarms, Section.Documents)
        assertEquals(nav, decodeNav(nav.encode()))
        assertEquals(NavState(), decodeNav(null)); assertEquals(NavState(), decodeNav("nonsense"))
        assertEquals(NavState(Primary.Planner, Section.Calendar, Section.Notes), decodeNav("Planner,Notes,Alarms"))  // a screen in the wrong group is ignored
        assertEquals(NavState(Primary.Talk, Section.Calendar, Section.Notes), decodeNav("Talk,Calendar,Notes"))  // a position saved by the four-destination app still restores
        assertEquals(Section.Home, decodeNav("Home,Calendar,Notes").current)
    }
}
