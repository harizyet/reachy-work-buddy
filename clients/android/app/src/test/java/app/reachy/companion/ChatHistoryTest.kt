package app.reachy.companion

import app.reachy.companion.data.ChatDetail
import app.reachy.companion.data.ChatTurnRecord
import app.reachy.companion.data.WebSearch
import app.reachy.companion.data.WebSource
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatHistoryTest {
    @Test fun `a saved chat is shown as each message followed by its reply`() {
        val sources = listOf(WebSource(title = "Docs", url = "https://example.com"))
        val lines = chatLines(ChatDetail("c1", "t", listOf(
            ChatTurnRecord("is it free?", "Yes [S1]", "complete", WebSearch(query = "q", results = sources)),
            ChatTurnRecord("and the cloud?", "It has a free tier."),
        )))
        assertEquals(listOf(true, false, true, false), lines.map { it.fromOwner })
        assertEquals(listOf("is it free?", "Yes [S1]", "and the cloud?", "It has a free tier."), lines.map { it.text })
        assertEquals(sources, lines[1].sources)
        assertTrue(lines.none { it.failed })
    }

    @Test fun `a message with no recorded reply is marked as not answered`() {
        val lines = chatLines(ChatDetail("c1", "t", listOf(ChatTurnRecord("anyone there?", null, "unknown"), ChatTurnRecord("ok", "fine"))))
        assertEquals(3, lines.size)
        assertTrue(lines[0].failed && lines[0].fromOwner)
        assertFalse(lines[1].failed)
        assertEquals(emptyList<ChatLine>(), chatLines(ChatDetail("c2")))
    }
}
