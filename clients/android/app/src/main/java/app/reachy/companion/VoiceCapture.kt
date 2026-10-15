package app.reachy.companion

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
import app.reachy.companion.data.CAPTURE_RATE
import app.reachy.companion.data.Endpointer
import app.reachy.companion.data.FRAME_SAMPLES
import app.reachy.companion.data.Wav
import app.reachy.companion.data.frameDbfs
import kotlin.math.max

/**
 * The one microphone path for voice that Reachy's own services hear (Phase 32A.V, ADR 0041): captures a single utterance as mono 16 kHz PCM16,
 * entirely in memory, and hands back a WAV. The same bytes are what the hub transcribes and what the speaker check reads, so there is no second
 * microphone consumer. Nothing is written to disk or logged. Same shape as [SpeechInput]: start() listens for one utterance, then ends.
 */
class PcmCapture(
    private val onLevel: (Float) -> Unit = {},
    private val onUtterance: (ByteArray) -> Unit,
    private val onEnd: (String?) -> Unit,
    private val maxSeconds: Int = 20,
    private val noSpeechSeconds: Int = 8,
) {
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var generation = 0
    private var thread: Thread? = null

    @SuppressLint("MissingPermission")   // callers check RECORD_AUDIO first
    fun start() {
        stop()
        val mine = ++generation
        thread = Thread({ run(mine) }, "pcm-capture").also { it.start() }
    }

    /** Stops listening and releases the microphone before returning; no callback follows. */
    fun stop() {
        generation++
        thread?.let { runCatching { it.join(1500) } }
        thread = null
    }

    @SuppressLint("MissingPermission")
    private fun run(mine: Int) {
        val minBuffer = AudioRecord.getMinBufferSize(CAPTURE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (minBuffer <= 0) { finish(mine, null, "This phone cannot record at 16 kHz"); return }
        val record = runCatching {
            AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, CAPTURE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, max(minBuffer, FRAME_SAMPLES * 8))
        }.getOrNull()
        if (record == null || record.state != AudioRecord.STATE_INITIALIZED) { record?.release(); finish(mine, null, "The microphone is in use or unavailable"); return }
        val endpointer = Endpointer(noSpeechFrames = noSpeechSeconds * 1000 / 30, maxFrames = maxSeconds * 1000 / 30)
        var pcm = ShortArray(CAPTURE_RATE * (maxSeconds + 1))
        var length = 0
        val frame = ShortArray(FRAME_SAMPLES)
        try {
            record.startRecording()
            while (mine == generation) {
                var got = 0
                while (got < FRAME_SAMPLES && mine == generation) {
                    val n = record.read(frame, got, FRAME_SAMPLES - got)
                    if (n <= 0) { finish(mine, null, "The microphone stopped"); return }
                    got += n
                }
                if (mine != generation) return
                if (length + FRAME_SAMPLES > pcm.size) pcm = pcm.copyOf(pcm.size * 2)
                System.arraycopy(frame, 0, pcm, length, FRAME_SAMPLES); length += FRAME_SAMPLES
                val db = frameDbfs(frame)
                main.post { if (mine == generation) onLevel(((db + 55f) / 40f).coerceIn(0f, 1f)) }
                when (endpointer.feed(db)) {
                    Endpointer.Event.Ended, Endpointer.Event.TooLong -> {
                        val from = endpointer.keepFrom()
                        finish(mine, Wav.encode(pcm.copyOfRange(from, length)), null); return
                    }
                    Endpointer.Event.NoSpeech -> { finish(mine, null, null); return }
                    else -> {}
                }
            }
        } catch (e: IllegalStateException) {
            finish(mine, null, "The microphone stopped")
        } finally {
            runCatching { record.stop() }; record.release()
            pcm.fill(0)   // the clip is the owner's voice: do not leave it behind in memory we still hold
        }
    }

    private fun finish(mine: Int, wav: ByteArray?, error: String?) {
        main.post {
            if (mine != generation) return@post
            if (wav != null) onUtterance(wav)
            onEnd(error)
        }
    }
}
