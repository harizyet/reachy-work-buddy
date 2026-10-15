package app.reachy.companion

import app.reachy.companion.data.AudioGaps
import app.reachy.companion.data.Meeting
import app.reachy.companion.data.Segment
import app.reachy.companion.data.countOccurrences
import app.reachy.companion.data.gapNotice
import app.reachy.companion.data.lineAt
import app.reachy.companion.data.lineIsSilent
import app.reachy.companion.data.silentSeconds
import app.reachy.companion.data.segmentText
import app.reachy.companion.data.speakerDisplayName
import app.reachy.companion.data.speakerAt
import app.reachy.companion.data.speakerFor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TranscriptTest {
    private val meeting = Meeting(
        id = "m", title = "T",
        transcript = listOf(Segment(0.0, 6.0, " We try Germanite. "), Segment(6.0, 10.0, "Agreed.")),
        speakers = listOf(Segment(0.0, 2.0, speaker = "SPEAKER_00"), Segment(2.0, 10.0, speaker = "SPEAKER_01")),
        speakerNames = mapOf("SPEAKER_01" to "Tom"),
        corrections = mapOf("0" to "We try Gemini."),
    )

    @Test fun `a segment belongs to the speaker with the most overlap`() {
        assertEquals("SPEAKER_01", speakerFor(meeting, meeting.transcript!![0]))
        assertEquals("SPEAKER_01", speakerFor(meeting, meeting.transcript!![1]))
    }

    @Test fun `the playing position maps to the line being spoken`() {
        val lines = meeting.transcript!!
        assertEquals(0, lineAt(lines, 0.0)); assertEquals(0, lineAt(lines, 5.99)); assertEquals(1, lineAt(lines, 6.0))
        assertNull(lineAt(lines, 10.0)); assertNull(lineAt(emptyList(), 1.0))
    }

    @Test fun `silent stretches are reported and the affected lines flagged`() {
        assertEquals(0.0, silentSeconds(meeting), 0.0); assertEquals(false, lineIsSilent(meeting, 0))
        val gappy = meeting.copy(audioGaps = AudioGaps(seconds = 511.0, segments = listOf(1)))
        assertEquals(511.0, silentSeconds(gappy), 0.0)
        assertEquals(true, lineIsSilent(gappy, 1)); assertEquals(false, lineIsSilent(gappy, 0))
        assertEquals(true, gapNotice(gappy).startsWith("8:31 of this recording has no audio"))
    }

    @Test fun `no diarization means no speaker`() {
        assertNull(speakerFor(meeting.copy(speakers = null), meeting.transcript!![0]))
    }

    @Test fun `owner names win and unnamed speakers get friendly numbers`() {
        assertEquals("Tom", speakerDisplayName(meeting, "SPEAKER_01"))
        assertEquals("Speaker 1", speakerDisplayName(meeting, "SPEAKER_00"))
        assertEquals("Host", speakerDisplayName(meeting, "Host"))
    }

    @Test fun `accepted corrections overlay the raw text which is trimmed otherwise`() {
        assertEquals("We try Gemini.", segmentText(meeting, 0))
        assertEquals("Agreed.", segmentText(meeting, 1))
        assertEquals("", segmentText(meeting, 7))
    }

    @Test fun `counting uses whole words, ignores case and sees corrected text`() {
        val m = meeting.copy(
            transcript = listOf(Segment(0.0, 1.0, "Germanite and germanite"), Segment(1.0, 2.0, "Germanites differ"), Segment(2.0, 3.0, "none")),
            corrections = mapOf("2" to "Germanite again"),
        )
        assertEquals(2, countOccurrences(m, "Germanite"))
        assertEquals(0, countOccurrences(m, "  "))
    }

    @Test fun `the stored alignment wins and the overlap is only a fallback`() {
        val stored = meeting.copy(aligned = listOf(Segment(0.0, 6.0, "x", "SPEAKER_00"), Segment(6.0, 10.0, "y", "SPEAKER_01")))
        assertEquals("SPEAKER_00", speakerAt(stored, 0, stored.transcript!![0]))  // the overlap alone would say SPEAKER_01
        assertEquals("SPEAKER_01", speakerAt(meeting, 0, meeting.transcript!![0]))  // not aligned yet: computed
        val wrongLength = meeting.copy(aligned = listOf(Segment(0.0, 1.0, "x", "SPEAKER_00")))
        assertEquals("SPEAKER_01", speakerAt(wrongLength, 0, wrongLength.transcript!![0]))  // a stale or short alignment is ignored
    }
}
