package app.reachy.companion

import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioTrack
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** One-shot dictation using the phone's own recognizer. Must be used from the main thread. */
class SpeechInput(
    private val context: Context,
    private val onPartial: (String) -> Unit,
    private val onFinal: (String) -> Unit,
    private val onEnd: (error: String?) -> Unit,
    private val onLevel: (Float) -> Unit = {},
) {
    private var recognizer: SpeechRecognizer? = null

    fun start() {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) { onEnd("Speech recognition is not available on this phone"); return }
        stop()
        recognizer = SpeechRecognizer.createSpeechRecognizer(context).also { sr ->
            sr.setRecognitionListener(object : RecognitionListener {
                override fun onResults(results: Bundle) {
                    val text = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                    if (text.isNotBlank()) onFinal(text)
                    onEnd(null)
                    release()
                }
                override fun onPartialResults(partial: Bundle) {
                    partial.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let(onPartial)
                }
                override fun onError(error: Int) {
                    onEnd(if (error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT) null else "Could not hear that (code $error)")
                    release()
                }
                override fun onReadyForSpeech(params: Bundle?) {}
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(rmsdB: Float) { onLevel(((rmsdB + 2f) / 12f).coerceIn(0f, 1f)) }
                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() {}
                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
            sr.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            })
        }
    }

    /** Frees the recogniser once it has finished (some phones keep the media volume muted until it is destroyed). */
    private fun release() { Handler(Looper.getMainLooper()).post { stop() } }

    fun stop() { recognizer?.destroy(); recognizer = null }
}

class SpeechOutput(private val context: Context) {
    private var ready = false
    private var waiting: String? = null   // a reply asked for before the engine finished starting
    private val tts: TextToSpeech = TextToSpeech(context) { status ->
        ready = status == TextToSpeech.SUCCESS
        // A freshly opened Talk screen can have a reply to read before the phone's engine is up; read it as soon as it is.
        waiting?.let { text -> waiting = null; if (ready) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "reply") }
    }
    private var spokenDone: (() -> Unit)? = null   // runs once when the phone's voice finishes; dropped when it is interrupted
    private var player: MediaPlayer? = null
    private val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private var focus: AudioFocusRequest? = null

    init {
        val finished = { Handler(Looper.getMainLooper()).post { spokenDone?.let { spokenDone = null; it() } }; Unit }
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) { finished() }
            @Deprecated("Deprecated in Java") override fun onError(utteranceId: String?) { finished() }
        })
    }

    /** The phone's own voice: the fallback when Reachy's voice cannot be fetched or played. [onDone] runs when it has finished. */
    fun speak(text: String, onDone: () -> Unit = {}) {
        stopPlayer()
        spokenDone = onDone
        if (ready) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "reply") else waiting = text
    }

    private var pcm: PcmPlayer? = null

    /**
     * Plays Reachy's voice as it arrives from the hub, so speech starts after the first sentence rather than the whole reply.
     * [fetch] reports the sample rate, then raw 16-bit mono PCM, and returns false if the hub could not speak. When nothing
     * could be played, [onFallback] runs (the caller then uses the phone's own voice); [onDone] runs once the audio has finished.
     */
    fun playStream(
        scope: CoroutineScope,
        fetch: suspend (onRate: (Int) -> Unit, onPcm: (ByteArray, Int) -> Unit) -> Boolean,
        onFallback: () -> Unit,
        onDone: () -> Unit,
    ) {
        stop()
        focus = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK).setAudioAttributes(speechAttributes).build()
            .also { audio.requestAudioFocus(it) }
        pcm = PcmPlayer(speechAttributes).also { it.play(scope, fetch, { stopPlayer(); onFallback() }, { stopPlayer(); onDone() }) }
    }

    private val speechAttributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()

    private fun stopPlayer() {
        pcm?.stop(); pcm = null
        player?.release(); player = null
        focus?.let { audio.abandonAudioFocusRequest(it) }; focus = null
    }
    fun stop() { spokenDone = null; tts.stop(); stopPlayer() }
    fun shutdown() { stopPlayer(); tts.shutdown() }
}

/** Plays a stream of raw 16-bit mono PCM through an AudioTrack while it is still downloading. Main thread only. */
class PcmPlayer(private val attributes: AudioAttributes) {
    private var track: AudioTrack? = null
    private var job: Job? = null

    fun play(
        scope: CoroutineScope,
        fetch: suspend (onRate: (Int) -> Unit, onPcm: (ByteArray, Int) -> Unit) -> Boolean,
        onFallback: () -> Unit,
        onDone: () -> Unit,
    ) {
        job = scope.launch(Dispatchers.IO) {
            var frames = 0L
            var carry: Byte? = null   // a network read can end in the middle of a 16-bit sample
            var ok = false
            try {
                ok = fetch(
                    { rate ->
                        val minimum = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
                        track = AudioTrack.Builder()
                            .setAudioAttributes(attributes)
                            .setAudioFormat(AudioFormat.Builder().setSampleRate(rate).setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                            .setBufferSizeInBytes(maxOf(minimum, rate * 2))   // about a second, to ride out a slow sentence
                            .setTransferMode(AudioTrack.MODE_STREAM)
                            .build().also { it.play() }
                    },
                    { buffer, count ->
                        val t = track
                        if (t != null && isActive) {
                            val data = if (carry == null) buffer.copyOf(count) else byteArrayOf(carry!!) + buffer.copyOf(count)
                            val usable = data.size - data.size % 2
                            carry = if (usable < data.size) data[usable] else null
                            if (usable > 0 && t.write(data, 0, usable) > 0) frames += usable / 2
                        }
                    },
                )
            } catch (e: Exception) { /* a stream that breaks after audio has started simply ends */ }
            val t = track
            if (!isActive) return@launch
            if (t == null || frames == 0L) { withContext(Dispatchers.Main) { if (isActive) onFallback() }; return@launch }
            // Everything is written; wait for the speaker to play it out.
            while (isActive && t.playbackHeadPosition < frames) delay(50)
            if (isActive) withContext(Dispatchers.Main) { if (isActive) onDone() }
        }
    }

    fun stop() {
        job?.cancel(); job = null
        track?.let { runCatching { it.pause(); it.flush(); it.release() } }; track = null
    }
}

/** Records one AAC/m4a clip for the meeting uploader (the hub accepts .m4a). */
class MeetingRecorder(private val context: Context) {
    private var recorder: MediaRecorder? = null
    private var file: File? = null

    fun start() {
        val target = File(context.cacheDir, "recording-${System.currentTimeMillis()}.m4a")
        val r = if (Build.VERSION.SDK_INT >= 31) MediaRecorder(context) else @Suppress("DEPRECATION") MediaRecorder()
        r.setAudioSource(MediaRecorder.AudioSource.MIC)
        r.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
        r.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
        r.setAudioSamplingRate(16000)
        r.setAudioEncodingBitRate(64000)
        r.setOutputFile(target.absolutePath)
        r.prepare()
        r.start()
        recorder = r
        file = target
    }

    /** Returns the finished clip, or null when nothing usable was captured. */
    fun stop(): File? {
        val r = recorder ?: return null
        recorder = null
        val ok = runCatching { r.stop() }.isSuccess
        r.release()
        return file?.takeIf { ok && it.length() > 0 }.also { if (it == null) file?.delete() }
    }

    fun cancel() { stop()?.delete() }
}
