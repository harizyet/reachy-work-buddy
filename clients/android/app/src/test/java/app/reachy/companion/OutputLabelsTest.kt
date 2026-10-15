package app.reachy.companion

import app.reachy.companion.data.tierLabel
import app.reachy.companion.data.writingLine
import app.reachy.companion.data.tierTag
import app.reachy.companion.data.writtenAt
import org.junit.Assert.assertEquals
import org.junit.Test

class OutputLabelsTest {
    @Test fun `every tier is named in words and an unknown one is shown as it came`() {
        assertEquals("the local model", tierLabel("local")); assertEquals("the larger local model", tierLabel("deep")); assertEquals("the cloud model", tierLabel("cloud"))
        assertEquals("mystery", tierLabel("mystery"))
    }

    @Test fun `a finished output states its tier and time and an in-progress one states the tier it is running on`() {
        assertEquals(listOf("Quick local", "Deep local", "Cloud", "mystery"), listOf("local", "deep", "cloud", "mystery").map(::tierTag))
        assertEquals("2026-10-15 02:07", writtenAt("2026-10-15T02:07:48.960209Z")); assertEquals("", writtenAt(""))
        assertEquals("Writing the summary on the larger local model…", writingLine("summary", "deep"))
        assertEquals("Writing the minutes on the cloud model…", writingLine("minutes", "cloud"))
    }
}
