package app.reachy.companion

import app.reachy.companion.data.HandoffOutcome
import app.reachy.companion.data.HandoffState
import app.reachy.companion.data.RecorderResult
import app.reachy.companion.data.RecordingHandoff
import app.reachy.companion.data.isMeetingRecordingCommand
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** "Reachy, begin meeting recording": which sentences are the command, and the ordering and stale-callback guards of the handoff. */
@OptIn(ExperimentalCoroutinesApi::class)
class RecordingHandoffTest {
    @Test fun `the explicit phrases are commands`() {
        for (phrase in listOf(
            "Begin meeting recording", "Start meeting recording", "Start recording this meeting", "Record this meeting", "Reachy, begin meeting recording.",
            "Hey Reachy, record this meeting", "start recording the meeting please", "Can you record this meeting", "begin meeting recording!", "Start a meeting recording",
        )) assertTrue(phrase, isMeetingRecordingCommand(phrase))
    }

    @Test fun `questions and longer sentences that only mention recording are ordinary conversation`() {
        for (phrase in listOf(
            "What happens when I record a meeting?", "How do I start meeting recording", "Do I need to record this meeting", "Tell me about my last meeting recording",
            "Record this meeting and email it to Sam", "Don't record this meeting", "I record meetings every day", "Stop meeting recording", "Add a task to record the meeting", "", "Reachy",
            "Delete the meeting recording", "Start the meeting",
        )) assertFalse(phrase, isMeetingRecordingCommand(phrase))
    }

    private class Fake(val scope: TestScope) : RecordingHandoff.Host {
        val log = mutableListOf<String>()
        val outcomes = mutableListOf<HandoffOutcome>()
        var mic = true
        var recording = false
        var foreground = true
        var canSpeak = true
        var startThrows = false
        var recorder = CompletableDeferred<RecorderResult>()
        var lastOperation = 0
        override fun microphoneAllowed() = mic
        override fun recordingActive() = recording
        override fun appInForeground() = foreground
        override fun speakConfirmation(operation: Int): Boolean { log += "speak"; lastOperation = operation; return canSpeak }
        override fun endVoice() { log += "endVoice" }
        override fun requestRecorderStart() { log += "start"; if (startThrows) throw IllegalStateException("no") }
        override suspend fun awaitRecorder(): RecorderResult = recorder.await()
        override fun finished(outcome: HandoffOutcome) { log += "finished"; outcomes += outcome }
    }

    private fun TestScope.setup(): Pair<RecordingHandoff, Fake> { val fake = Fake(this); return RecordingHandoff(this, fake) to fake }

    @Test fun `confirmation first, then voice ends, then the recorder starts, and success is only reported once the recorder is active`() = runTest {
        val (handoff, fake) = setup()
        assertTrue(handoff.begin())
        assertEquals(HandoffState.Confirming, handoff.state)
        assertEquals(listOf("speak"), fake.log)
        handoff.confirmationFinished(fake.lastOperation, spoken = true)
        advanceUntilIdle()
        assertEquals(listOf("speak", "endVoice", "start"), fake.log)   // voice is closed before the recorder is asked for the microphone
        assertEquals(HandoffState.StartingRecording, handoff.state)
        assertTrue("a request being accepted is not a recording", fake.outcomes.isEmpty())
        fake.recorder.complete(RecorderResult.Active)
        advanceUntilIdle()
        assertEquals(listOf<HandoffOutcome>(HandoffOutcome.Started), fake.outcomes)
        assertEquals(HandoffState.Idle, handoff.state)
    }

    @Test fun `a recorder that fails is reported as a failure, never as started`() = runTest {
        val (handoff, fake) = setup()
        handoff.begin(); handoff.confirmationFinished(fake.lastOperation, true)
        fake.recorder.complete(RecorderResult.Failed("Could not start recording"))
        advanceUntilIdle()
        assertEquals(listOf<HandoffOutcome>(HandoffOutcome.Failed("Could not start recording", resumeVoice = false)), fake.outcomes)
    }

    @Test fun `a recorder request that throws is a failure`() = runTest {
        val (handoff, fake) = setup()
        fake.startThrows = true
        handoff.begin(); handoff.confirmationFinished(fake.lastOperation, true)
        advanceUntilIdle()
        assertTrue(fake.outcomes.single() is HandoffOutcome.Failed)
        assertEquals(HandoffState.Idle, handoff.state)
    }

    @Test fun `a confirmation that fails or is interrupted starts nothing and the conversation can resume`() = runTest {
        val (handoff, fake) = setup()
        handoff.begin(); handoff.confirmationFinished(fake.lastOperation, spoken = false)
        advanceUntilIdle()
        assertFalse("start" in fake.log); assertFalse("endVoice" in fake.log)
        assertTrue((fake.outcomes.single() as HandoffOutcome.Failed).resumeVoice)
    }

    @Test fun `nothing that can speak means nothing is recorded`() = runTest {
        val (handoff, fake) = setup()
        fake.canSpeak = false
        handoff.begin()
        assertFalse("start" in fake.log)
        assertTrue(fake.outcomes.single() is HandoffOutcome.Failed)
        assertEquals(HandoffState.Idle, handoff.state)
    }

    @Test fun `without the microphone permission nothing is spoken or recorded`() = runTest {
        val (handoff, fake) = setup()
        fake.mic = false
        handoff.begin()
        assertEquals(listOf("finished"), fake.log)
        assertTrue((fake.outcomes.single() as HandoffOutcome.Failed).message.contains("Microphone permission"))
    }

    @Test fun `permission revoked while Reachy was speaking stops the handoff before the voice is closed`() = runTest {
        val (handoff, fake) = setup()
        handoff.begin(); fake.mic = false
        handoff.confirmationFinished(fake.lastOperation, true)
        assertEquals(listOf("speak", "finished"), fake.log)
    }

    @Test fun `an existing recording is never duplicated`() = runTest {
        val (handoff, fake) = setup()
        fake.recording = true
        handoff.begin()
        assertEquals(listOf("finished"), fake.log)
        assertEquals(listOf<HandoffOutcome>(HandoffOutcome.AlreadyRecording), fake.outcomes)
        // And one that started while the confirmation was being spoken.
        fake.log.clear(); fake.outcomes.clear(); fake.recording = false
        handoff.begin(); fake.recording = true
        handoff.confirmationFinished(fake.lastOperation, true)
        assertFalse("start" in fake.log)
        assertEquals(listOf<HandoffOutcome>(HandoffOutcome.AlreadyRecording), fake.outcomes)
    }

    @Test fun `a repeated command and a repeated completion start one recording`() = runTest {
        val (handoff, fake) = setup()
        assertTrue(handoff.begin())
        assertFalse(handoff.begin())   // a second command while the first is in progress is dropped
        handoff.confirmationFinished(fake.lastOperation, true)
        handoff.confirmationFinished(fake.lastOperation, true)   // a duplicate completion callback
        assertFalse(handoff.begin())
        advanceUntilIdle()
        assertEquals(1, fake.log.count { it == "start" })
        assertEquals(1, fake.log.count { it == "speak" })
        fake.recorder.complete(RecorderResult.Active); advanceUntilIdle()
    }

    @Test fun `cancelling during the confirmation records nothing, and the late completion is ignored`() = runTest {
        val (handoff, fake) = setup()
        handoff.begin()
        val stale = fake.lastOperation
        assertTrue(handoff.cancel("closed"))
        handoff.confirmationFinished(stale, true)   // the speech finished after the owner closed voice mode
        advanceUntilIdle()
        assertFalse("start" in fake.log); assertFalse("endVoice" in fake.log)
        assertEquals(listOf<HandoffOutcome>(HandoffOutcome.Cancelled("closed")), fake.outcomes)
    }

    @Test fun `a completion left over from a cancelled handoff cannot start the next one`() = runTest {
        val (handoff, fake) = setup()
        handoff.begin(); val old = fake.lastOperation
        handoff.cancel("closed")
        handoff.begin(); val current = fake.lastOperation
        handoff.confirmationFinished(old, true)
        assertEquals(HandoffState.Confirming, handoff.state)
        assertFalse("start" in fake.log)
        handoff.confirmationFinished(current, true)
        advanceUntilIdle()
        assertEquals(1, fake.log.count { it == "start" })
        fake.recorder.complete(RecorderResult.Active); advanceUntilIdle()
    }

    @Test fun `leaving the app is checked at the start and again after the confirmation`() = runTest {
        val (handoff, fake) = setup()
        fake.foreground = false
        handoff.begin()
        assertFalse("speak" in fake.log)
        assertTrue(fake.outcomes.single() is HandoffOutcome.Failed)

        fake.log.clear(); fake.outcomes.clear(); fake.foreground = true
        handoff.begin(); fake.foreground = false
        handoff.confirmationFinished(fake.lastOperation, true)
        assertFalse("start" in fake.log); assertFalse("endVoice" in fake.log)
        assertTrue(fake.outcomes.single() is HandoffOutcome.Failed)
    }

    @Test fun `once the recorder has been asked to start it cannot be cancelled, and the outcome still arrives`() = runTest {
        val (handoff, fake) = setup()
        handoff.begin(); handoff.confirmationFinished(fake.lastOperation, true)
        assertFalse(handoff.cancel("screen closed"))
        assertEquals(HandoffState.StartingRecording, handoff.state)
        fake.recorder.complete(RecorderResult.Active)
        advanceUntilIdle()
        assertEquals(listOf<HandoffOutcome>(HandoffOutcome.Started), fake.outcomes)
    }

    @Test fun `cancelling while the voice screen is closing prevents the start`() = runTest {
        val scope = this
        lateinit var handoff: RecordingHandoff
        val fake = object : RecordingHandoff.Host by Fake(scope) {
            val log = mutableListOf<String>()
            override fun microphoneAllowed() = true
            override fun recordingActive() = false
            override fun appInForeground() = true
            override fun speakConfirmation(operation: Int) = true
            override fun endVoice() { log += "endVoice"; handoff.cancel("owner closed it") }
            override fun requestRecorderStart() { log += "start" }
            override fun finished(outcome: HandoffOutcome) { log += "finished" }
        }
        handoff = RecordingHandoff(scope, fake)
        handoff.begin(); handoff.confirmationFinished(1, true)
        advanceUntilIdle()
        assertEquals(listOf("endVoice", "finished"), fake.log)
    }

    @Test fun `a typed command skips the spoken confirmation and still waits for the recorder`() = runTest {
        val (h, f) = setup()
        assertTrue(h.begin(speak = false))
        assertEquals(listOf("endVoice", "start"), f.log)
        assertTrue(f.outcomes.isEmpty())
        f.recorder.complete(RecorderResult.Active); advanceUntilIdle()
        assertEquals(listOf<HandoffOutcome>(HandoffOutcome.Started), f.outcomes)
    }

    @Test fun `a typed command with no microphone permission records nothing`() = runTest {
        val (h, f) = setup(); f.mic = false
        h.begin(speak = false)
        assertEquals(listOf("finished"), f.log)
    }
}
