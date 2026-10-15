package app.reachy.companion

import app.reachy.companion.data.Note
import app.reachy.companion.data.folderTrail
import app.reachy.companion.data.inNoteFolder
import app.reachy.companion.data.noteFolders
import app.reachy.companion.data.normaliseNoteTag
import app.reachy.companion.data.groupedNotes
import app.reachy.companion.data.joinNote
import app.reachy.companion.data.matchesNote
import app.reachy.companion.data.noteDate
import app.reachy.companion.data.notePreview
import app.reachy.companion.data.noteSection
import app.reachy.companion.data.splitNote
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.OffsetDateTime
import java.time.ZoneId
import java.util.Locale

class NotesTest {
    private val utc = ZoneId.of("UTC")
    private val now = OffsetDateTime.parse("2026-10-07T15:00:00Z")
    private fun ago(days: Long, hour: Int = 9) = now.minusDays(days).withHour(hour).toString()
    private fun note(id: String, title: String, daysAgo: Long, body: String = "") = Note(id, title, body, ago(daysAgo))

    @Test fun `the first line of the text is the title and the rest is the body`() {
        assertEquals("Groceries" to "milk\neggs", splitNote("Groceries\nmilk\neggs"))
        assertEquals("Idea" to "", splitNote("  Idea  "))
        assertEquals("Idea" to "later", splitNote("\n\nIdea\n\nlater"))
        assertNull(splitNote("   \n  "))
        assertEquals("Groceries\nmilk", joinNote("Groceries", "milk"))
        assertEquals("Idea", joinNote("Idea", ""))
        val long = "x".repeat(250)
        val (title, body) = splitNote("$long\nmore")!!
        assertEquals(200, title.length); assertEquals("x".repeat(50) + "\nmore", body)
    }

    @Test fun `notes are grouped under Today, Yesterday, recent ranges and months`() {
        val locale = Locale.US
        assertEquals("Today", noteSection(ago(0), now, utc, locale))
        assertEquals("Yesterday", noteSection(ago(1), now, utc, locale))
        assertEquals("Previous 7 Days", noteSection(ago(5), now, utc, locale))
        assertEquals("Previous 30 Days", noteSection(ago(20), now, utc, locale))
        assertEquals("July", noteSection(ago(80), now, utc, locale))
        assertEquals("October 2025", noteSection(ago(365), now, utc, locale))
        val grouped = groupedNotes(listOf(note("a", "old", 80), note("b", "new", 0), note("c", "mid", 1)), now, utc)
        assertEquals(listOf("Today", "Yesterday"), grouped.map { it.first }.take(2))
        assertEquals(listOf("new"), grouped[0].second.map { it.title })
    }

    @Test fun `row dates and previews follow the list conventions`() {
        assertEquals("Yesterday", noteDate(ago(1), now, utc, Locale.US))
        assertEquals("Friday", noteDate(ago(5), now, utc, Locale.US))  // 2026-10-02
        assertTrue(noteDate(ago(0, 9), now, utc, Locale.US).startsWith("9:00"))
        assertEquals("milk", notePreview(note("a", "t", 0, "\n  milk \nbread")))
        assertEquals("No additional text", notePreview(note("a", "t", 0)))
    }

    @Test fun `search matches title and text without regard to case`() {
        val n = note("a", "Baby Names", 0, "Chloe")
        assertTrue(matchesNote(n, "baby")); assertTrue(matchesNote(n, " chloe ")); assertTrue(matchesNote(n, ""))
        assertTrue(!matchesNote(n, "grocery"))
    }

    // The same cases as services/companion-core/tests/test_note_tag.py and clients/web/tests/folders.test.ts.
    @Test fun `a typed folder is normalised like the server does`() {
        assertNull(normaliseNoteTag(""))
        assertNull(normaliseNoteTag("  /  "))
        assertNull(normaliseNoteTag("All Notes"))
        assertEquals("Meeting Notes", normaliseNoteTag("Meeting Notes"))
        assertEquals("Meeting Notes", normaliseNoteTag("All Notes/Meeting Notes"))
        assertEquals("Projects/Project StarWars/Finance", normaliseNoteTag("all notes/Projects/Project StarWars/Finance"))
        assertEquals("Projects/Project StarWars/Finance", normaliseNoteTag(" Projects // Project   StarWars /Finance/ "))
        assertEquals("Projects/All Notes", normaliseNoteTag("Projects/All Notes"))
        assertEquals("a b/c d", normaliseNoteTag("a\nb/c\td"))
        assertEquals("a/b/c/d/e", normaliseNoteTag("a/b/c/d/e"))
        assertTrue(runCatching { normaliseNoteTag("a/b/c/d/e/f") }.isFailure)
        assertEquals("x".repeat(60), normaliseNoteTag("x".repeat(60)))
        assertTrue(runCatching { normaliseNoteTag("x".repeat(61)) }.isFailure)
    }

    @Test fun `the folder tree counts a folder with what is below it and a folder holds its descendants`() {
        fun filed(id: String, tag: String?) = Note(id, id, "", ago(0), tag)
        val notes = listOf(filed("a", "Projects/Finance"), filed("b", "projects"), filed("c", "Projects/Finance"), filed("d", "Alpha"), filed("e", null))
        assertEquals(
            listOf(Triple("Alpha", 0, 1), Triple("Projects", 0, 3), Triple("Projects/Finance", 1, 2)),
            noteFolders(notes).map { Triple(it.path, it.depth, it.count) },
        )
        assertTrue(inNoteFolder(filed("x", "Projects/Finance"), "Projects"))
        assertTrue(inNoteFolder(filed("x", "Projects"), "projects"))
        assertTrue(!inNoteFolder(filed("x", "Projects2"), "Projects"))
        assertTrue(!inNoteFolder(filed("x", null), "Projects"))
        assertTrue(inNoteFolder(filed("x", null), null))
        assertEquals("Notes", folderTrail(null))
        assertEquals("Projects \u203a Project StarWars \u203a Finance", folderTrail("Projects/Project StarWars/Finance"))
        assertTrue(matchesNote(filed("x", "Projects/Finance"), "finance"))
    }
}
