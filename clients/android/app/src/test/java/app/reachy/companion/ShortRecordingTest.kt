package app.reachy.companion

import app.reachy.companion.data.ShortVerdict
import app.reachy.companion.data.shortRecordingQuestion
import app.reachy.companion.data.shortRecordingVerdict
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ShortRecordingTest {
    @Test fun `under ten seconds is discarded, ten to under thirty asks, thirty and over is kept`() {
        assertEquals(ShortVerdict.Discard, shortRecordingVerdict(0))
        assertEquals(ShortVerdict.Discard, shortRecordingVerdict(9))
        assertEquals(ShortVerdict.Ask, shortRecordingVerdict(10))
        assertEquals(ShortVerdict.Ask, shortRecordingVerdict(29))
        assertEquals(ShortVerdict.Keep, shortRecordingVerdict(30))
        assertEquals(ShortVerdict.Keep, shortRecordingVerdict(3600))
    }

    @Test fun `the question names the length`() {
        assertTrue(shortRecordingQuestion(17).contains("only 17 seconds"))
    }
}
