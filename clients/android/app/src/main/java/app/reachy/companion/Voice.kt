package app.reachy.companion

import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFocusRequest
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
import java.io.File

/** One-shot dictation using the phone's own recognizer. Must be used from the main thread. */
class SpeechInput(
    private val context: Context,
    private val onPartial: (String) -> Unit,
    private val onFinal: (String) -> Unit,
    private val onEnd: (error: String?) -> Unit,
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
                override fun onRmsChanged(rmsdB: Float) {}
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
    private var player: MediaPlayer? = null
    private val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private var focus: AudioFocusRequest? = null

    /** The phone's own voice: the fallback when Reachy's voice cannot be fetched or played. */
    fun speak(text: String) {
        stopPlayer()
        if (ready) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "reply") else waiting = text
    }

    /** Plays a WAV in Reachy's voice; false when it cannot be played. [onError] runs if playback fails once it has started. */
    fun play(file: File, onError: () -> Unit = {}): Boolean {
        stop()
        return try {
            val attributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
            focus = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK).setAudioAttributes(attributes).build()
                .also { audio.requestAudioFocus(it) }
            player = MediaPlayer().apply {
                setAudioAttributes(attributes)
                setDataSource(file.absolutePath)
                setOnCompletionListener { stopPlayer() }
                setOnErrorListener { _, _, _ -> stopPlayer(); onError(); true }
                prepare(); start()
            }
            true
        } catch (e: Exception) { stopPlayer(); false }
    }

    private fun stopPlayer() {
        player?.release(); player = null
        focus?.let { audio.abandonAudioFocusRequest(it) }; focus = null
    }
    fun stop() { tts.stop(); stopPlayer() }
    fun shutdown() { stopPlayer(); tts.shutdown() }
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
