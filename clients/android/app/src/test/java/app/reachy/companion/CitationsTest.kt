package app.reachy.companion

import app.reachy.companion.data.Piece
import app.reachy.companion.data.WebSource
import app.reachy.companion.data.citedPieces
import app.reachy.companion.data.safeUrl
import app.reachy.companion.data.sourceLabel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class CitationsTest {
    private val sources = listOf(
        WebSource("ClickHouse FAQ", "https://clickhouse.com/docs/faq", sourceDomain = "clickhouse.com"),
        WebSource("Pricing", "http://example.org/pricing", sourceDomain = "example.org"),
        WebSource("Sneaky", "javascript:alert(1)", sourceDomain = "evil"),
    )

    @Test fun `known markers become links and unknown or unsafe ones stay plain text`() {
        val pieces = citedPieces("Open source [S1], paid cloud [S2], odd [S3], missing [S9].", sources)
        assertEquals(listOf("[S1]", "[S2]"), pieces.filterIsInstance<Piece.Cite>().map { it.label })
        assertEquals("https://clickhouse.com/docs/faq", (pieces.filterIsInstance<Piece.Cite>()[0]).url)
        // the text round-trips exactly, so nothing the model wrote is dropped or reinterpreted
        assertEquals("Open source [S1], paid cloud [S2], odd [S3], missing [S9].", pieces.joinToString("") { when (it) { is Piece.Text -> it.text; is Piece.Cite -> it.label } })
    }

    @Test fun `without sources the answer is one plain piece`() {
        assertEquals(listOf(Piece.Text("Hello [S1]")), citedPieces("Hello [S1]", emptyList()))
    }

    @Test fun `only http and https links without credentials are tappable`() {
        assertEquals("https://a.example/x", safeUrl("https://a.example/x"))
        assertNull(safeUrl("javascript:alert(1)")); assertNull(safeUrl("file:///etc/passwd")); assertNull(safeUrl("intent://x#Intent;end"))
        assertNull(safeUrl("https://user:pw@a.example/")); assertNull(safeUrl("not a url")); assertNull(safeUrl(""))
    }

    @Test fun `source labels carry the number the model cites`() {
        assertEquals("[S1] clickhouse.com: ClickHouse FAQ", sourceLabel(0, sources[0]))
        assertEquals("[S2] https://x.example", sourceLabel(1, WebSource("", "https://x.example")))
    }
}
